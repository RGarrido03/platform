# Huly Document Export to Markdown: Architectural Analysis & Implementation Guide

Comprehensive research report detailing Huly's document data architecture, collaborative state management, existing export mechanisms, and an end-to-end design for client-side and server-side Markdown export.

---

## 1. Executive Summary & Problem Framing

Huly features a real-time collaborative document system combining **ProseMirror/TipTap** rich text editing, **Y.js** conflict-free replicated data types (CRDTs), an authoritative **Hocuspocus** collaboration server, and distributed persistence across **CockroachDB** (metadata and entity state) and **MinIO/S3** (binary Y.js state snapshots and compressed markup JSON blobs).

While Huly possesses foundational packages for parsing and serializing markup to markdown (`@hcengineering/text-markdown`) and an action for copying issues to clipboard as Markdown (`CopyDocumentMarkdown`), it currently lacks a dedicated **"Export to Markdown"** workflow for Documents in `plugins/document`. Furthermore:
1. The existing serializer in `@hcengineering/text-markdown` lacks serialization rules for key Huly nodes such as embedded attachments (`file`) and drawing boards (`drawingBoard`), and renders all tables as raw HTML rather than GFM pipe tables.
2. Documents with embedded images rely on internal platform blob URIs (`platform://platform/files/...` or `image://file-id`) that are not portable without URL resolution or asset bundling.
3. No document action or menu item is registered on `document.class.Document` for downloading `.md` files or exporting entire document hierarchies as zipped folder trees.

This report outlines the complete architecture and provides concrete, minimal, and fully compatible implementations for both **client-side export** (instant download from the browser UI) and **server-side headless API export** (via Collaborator RPC and Transactor REST endpoints).

---

## 2. Document Storage, Modeling & Collaborative State Pipeline

### 2.1 Entity Data Modeling (`models/document` & `plugins/document`)

Huly defines documents using TypeScript class decorators in `models/document/src/index.ts`:

```typescript
export const DOMAIN_DOCUMENT = 'document' as Domain

@Model(document.class.Document, core.class.Doc, DOMAIN_DOCUMENT)
@UX(document.string.Document, document.icon.Document, undefined, 'name', undefined, document.string.Documents)
export class TDocument extends TDoc implements Document, Todoable {
  @Prop(TypeString(), document.string.Name)
  @Index(IndexKind.FullText)
  title!: string

  @Prop(TypeCollaborativeDoc(), document.string.Document)
  content!: MarkupBlobRef | null

  @Prop(TypeRef(document.class.Document), document.string.ParentDocument)
  parent!: Ref<Document>

  @Prop(TypeRef(core.class.Space), core.string.Space)
  @Index(IndexKind.Indexed)
  @Hidden()
  declare space: Ref<Teamspace>

  @Prop(TypeAccountUuid(), document.string.LockedBy)
  @Hidden()
  lockedBy?: AccountUuid

  @Prop(Collection(attachment.class.Embedding), attachment.string.Embeddings)
  embeddings?: number

  @Prop(Collection(attachment.class.Attachment), attachment.string.Attachments)
  attachments?: number

  @Prop(Collection(chunter.class.ChatMessage), chunter.string.Comments)
  comments?: number

  @Prop(Collection(tags.class.TagReference), document.string.Labels)
  labels?: number

  @Prop(TypeRank(), core.string.Rank)
  @Index(IndexKind.Indexed)
  @Hidden()
  rank!: Rank
}
```

Key characteristics:
- **`title`**: String property indexed for full-text search.
- **`content`**: Typed as `MarkupBlobRef | null` via `@Prop(TypeCollaborativeDoc())`. The document entity in CockroachDB does **not** store the entire document text in its JSONB column; it stores a string reference to a collaborative blob in object storage.
- **`parent`**: Self-referencing link to parent document. Root documents have `parent = document.ids.NoParent` (`"core:doc:nil"`).
- **`space`**: References the containing `Teamspace`.
- **`rank`**: Fractional indexing string (LexoRank) for ordering documents in the navigator tree.

### 2.2 Storage Layer & Persistence Topology

```
+-----------------------------------------------------------------------------------+
| CockroachDB: Table "document"                                                     |
| ("workspaceId", _id, space, title, parent, content: "673a...-content-170...", ...) |
+-----------------------------------------------------------------------------------+
                                         |
                                         | references content blob
                                         v
+-----------------------------------------------------------------------------------+
| MinIO / S3 Storage (Bucket: blobs)                                                |
|                                                                                   |
| 1. Binary Y.js Snapshot (CRDT):                                                  |
|    Blob ID: "${objectId}%content"                                                 |
|    Content-Type: "application/ydoc"                                               |
|                                                                                   |
| 2. Serialized Markup JSON (ProseMirror AST):                                      |
|    Blob ID: "${objectId}-content-${timestamp}"                                    |
|    Content-Type: "application/json"                                               |
+-----------------------------------------------------------------------------------+
```

1. **CockroachDB**: Stores the entity metadata in table `document` partitioned by `workspaceId`.
2. **MinIO / Storage Adapter**:
   - Y.js CRDT binary state: Key `${objectId}%${objectAttr}`, created via `makeCollabYdocId()`.
   - Frozen Markup JSON string: Key `${objectId}-${objectAttr}-${timestamp}`, created via `makeCollabJsonId()`.

### 2.3 Real-Time CRDT Pipeline (`server/collaborator` & `@hocuspocus/server`)

The `Collaborator` service (`server/collaborator`, port 3078) coordinates concurrent editing:
1. **Client Connection**: When a user opens a document, `CollaborativeTextEditor.svelte` connects via WebSocket to Collaborator with document identifier `encodeDocumentId(workspaceUuid, collabDoc)` where `collabDoc = { objectClass: 'document:class:Document', objectId: doc._id, objectAttr: 'content' }`.
2. **Memory CRDT**: Collaborator loads or instantiates a `Y.Doc`. If not in memory:
   - It attempts to load the binary Y.js state from storage using `loadCollabYdoc(ctx, storage, wsIds, documentId)`.
   - If no Y.js state exists, it loads the initial content JSON blob via `loadCollabJson(ctx, storage, wsIds, content)` and converts it to a Y.Doc using `markupToYDoc(markup, 'content')`.
3. **Synchronization**: Connected clients synchronize keystrokes in real time via Y.js delta protocol.
4. **Debounced Persistence**:
   - Every 10 seconds of idle (or max 60s), Collaborator triggers `onStoreDocument`.
   - Saves binary Y.js buffer via `saveCollabYdoc`.
   - Converts the live Y.Doc to `Markup` via `MarkupTransformer.fromYdoc(ydoc, 'content')` (`yDocToMarkup`).
   - Writes the JSON string to MinIO via `saveCollabJson` -> returns new `blobId`.
   - Commits a transaction to Transactor: `client.diffUpdate(current, { content: blobId })`.

### 2.4 Huly Rich-Text AST: `MarkupNode` & `MarkupMark`

Huly uses `@hcengineering/text-core` for its rich text model:
- `Markup` is defined as a serialized JSON string representing a `MarkupNode` tree.
- `MarkupNode` structure:
  ```typescript
  export interface MarkupNode {
    type: MarkupNodeType     // 'doc', 'paragraph', 'heading', 'table', etc.
    content?: MarkupNode[]   // Array of children
    marks?: MarkupMark[]     // Inline styles: bold, italic, link, textColor, etc.
    attrs?: Attrs            // Node attributes (level, language, src, file-id, etc.)
    text?: string            // Text content for text nodes
  }
  ```

Huly rich-text nodes map directly to ProseMirror/TipTap concepts:
- **Block Nodes**: `doc`, `paragraph`, `heading`, `blockquote`, `codeBlock`, `mermaid`, `markdown`, `bulletList`, `orderedList`, `listItem`, `taskList`, `taskItem`, `todoList`, `todoItem`, `table`, `tableRow`, `tableHeader`, `tableCell`, `comment`, `embed`, `horizontalRule`.
- **Inline / Leaf Nodes**: `text`, `image`, `file`, `reference`, `emoji`, `hardBreak`, `subLink`, `drawingBoard`.
- **Marks**: `bold`, `italic` (`em`), `strike`, `underline`, `code`, `link`, `textColor`, `textStyle`, `highlight`, `subscript`, `superscript`.

---

## 3. Existing Export & Print Services Review

| Service / Package | Monorepo Path | Functionality | Relevance to Document Markdown Export |
|---|---|---|---|
| **`pod-print`** | `services/print/pod-print` | Headless Chromium (Puppeteer) service. Converts URLs to PDF/PNG/WebP. | High-fidelity print/PDF engine. Not suitable for lightweight, editable Markdown export. |
| **`pod-export`** | `services/export/pod-export` | Workspace data migration service (`/export-to-workspace`, `/exportSync?format=csv`). | Migrates database entities and blobs between workspaces or exports metadata to CSV. Does not format rich text to Markdown. |
| **`rekoni`** | `services/rekoni`, `packages/rekoni` | Resume and document parsing service (PDF/DOCX to JSON/text). | Ingestion/extraction only; reverse direction. |
| **`text-markdown`** | `foundations/core/packages/text-markdown` | Two-way converter: `markupToMarkdown` and `markdownToMarkup`. | **The core engine for Markdown export.** Requires extensions for attachments (`file`), drawing boards, and GFM pipe tables. |
| **`view-resources`** | `plugins/view-resources` | Contains `CopyDocumentMarkdown` action. | Currently copies issue/card content to clipboard. Can be leveraged as a pattern for document export. |

---

## 4. Architectural Comparison: Client-Side vs Server-Side

```
+----------------------------------------------------------------------------------------------------+
|                                CLIENT-SIDE EXPORT (Recommended Primary)                            |
|                                                                                                    |
|  [Document Editor / UI Action]                                                                    |
|           |                                                                                        |
|           +---> Active Doc: Read live TipTap editor JSON via editor.getJSON()                      |
|           +---> Passive Doc: Fetch Markup via getMarkup(collabDoc, doc.content)                    |
|                      |                                                                             |
|                      v                                                                             |
|           [markupToMarkdown(markupNode, options)]                                                  |
|                      |                                                                             |
|           +----------+------------------------------------------+                                  |
|           | Single .md File                                     | Zipped Bundle (.zip)             |
|           v                                                     v                                  |
|     Blob([markdown])                                    JSZip:                                     |
|     saveAs(`${title}.md`)                               - `${title}.md` (rewritten links)          |
|                                                         - `/assets/${imageName}` (fetched blobs)   |
|                                                         saveAs(`${title}.zip`)                     |
+----------------------------------------------------------------------------------------------------+

+----------------------------------------------------------------------------------------------------+
|                                SERVER-SIDE / HEADLESS API EXPORT                                   |
|                                                                                                    |
|  [External Tool / Pytest / CI / cURL]                                                              |
|           |                                                                                        |
|           v                                                                                        |
|  GET /api/v1/documents/:id/export/markdown (Transactor or Collaborator RPC)                        |
|  Header: Authorization: Bearer <API_TOKEN>                                                         |
|           |                                                                                        |
|           +---> Query Document entity from CockroachDB                                             |
|           +---> Fetch Markup from Collaborator via getContent RPC or loadCollabJson                |
|           +---> Serialize via markupToMarkdown(markupNode, { resolveUrls: true })                   |
|           v                                                                                        |
|  Response: 200 OK                                                                                  |
|  Content-Type: text/markdown; charset=utf-8                                                        |
|  Content-Disposition: attachment; filename="Architecture.md"                                       |
+----------------------------------------------------------------------------------------------------+
```

### 4.1 Client-Side Approach (Instant Browser Download)

#### Advantages:
1. **Zero Server Load**: No Puppeteer instances, headless browsers, or CPU-intensive server workers required.
2. **Instant & Real-Time**: If the user is currently typing in the document, `editor.getJSON()` exports uncommitted, in-memory keystrokes that have not yet reached the 10-second debounce flush to MinIO.
3. **Direct File System Access**: Uses standard browser `URL.createObjectURL(blob)` and `<a download>` trigger.
4. **Secure**: Reuses the user's active session token; requires no additional permissions or endpoints.

#### Implementation Flow:
1. User clicks "Export to Markdown" in the Document header menu or navigator tree.
2. The action handler checks if the document is active in `CollaboratorEditor`.
   - If active: extract AST directly via `editor.getJSON()`.
   - If inactive: invoke `getMarkup(makeDocCollabId(doc, 'content'), doc.content)` from `@hcengineering/presentation`, which queries the Collaborator RPC.
3. Transform `MarkupNode` to Markdown string using `markupToMarkdown()`.
4. Prepend optional YAML frontmatter with metadata (title, space, author, dates).
5. Trigger browser download of `${sanitizeFilename(doc.title)}.md`.

### 4.2 Server-Side Approach (Collaborator / Transactor API)

#### Advantages:
1. **Automated Headless Access**: Enables external CLI tools, CI/CD pipelines, documentation generators, and backup scripts to fetch Markdown documents programmatically.
2. **Bulk Server-Side Archival**: Can package large spaces with hundreds of documents without consuming browser memory.

#### Implementation Flow:
1. Expose a new RPC method in `server/collaborator/src/rpc/methods/exportMarkdown.ts`:
   ```typescript
   export async function exportMarkdown(
     ctx: MeasureContext,
     context: Context,
     documentName: string,
     payload: ExportMarkdownRequest,
     params: RpcMethodParams
   ): Promise<ExportMarkdownResponse>
   ```
2. The method connects to Hocuspocus (`hocuspocus.openDirectConnection`), retrieves the `Y.Doc`, converts to `MarkupNode` via `transformer.fromYdoc()`, calls `markupToMarkdown()`, and returns `{ markdown: string, title: string }`.
3. An HTTP GET route `/api/v1/documents/:id/export/markdown` is mounted on the front/transactor server accepting API tokens.

---

## 5. Content Type & Formatting Deep-Dive

### 5.1 Tables: GFM Pipe Tables vs. HTML Fallback

In Huly's current `serializer.ts`:
```typescript
table: (state, node) => {
  state.write(state.renderHtml(node))
  state.closeBlock(node)
}
```
Tables are converted to HTML (`<table><tbody><tr><td>...</td></tr></tbody></table>`). While compliant with Markdown, users typically expect GitHub Flavored Markdown (GFM) pipe tables:

```markdown
| Column A | Column B |
| -------- | -------- |
| Value 1  | Value 2  |
```

#### Proposed Enhanced Table Serializer:
An intelligent serializer checks whether table cells contain complex nested blocks (e.g., lists, blockquotes, multiple paragraphs) or `colspan`/`rowspan` attributes:
- **Simple Tables (Single-line cells, no row/colspans)**: Output clean GFM pipe tables with aligned header delimiters.
- **Complex Tables**: Gracefully fall back to HTML `<table>` representation to preserve document structure.

```typescript
function serializeTableToGfmOrHtml(state: IState, node: MarkupNode): void {
  const rows = node.content?.filter((n) => n.type === MarkupNodeType.table_row) ?? []
  
  // Check for colspans, rowspans, or complex nested blocks
  const isComplex = rows.some((row) =>
    row.content?.some((cell) => {
      const attrs = cell.attrs ?? {}
      if (Number(attrs.colspan ?? 1) > 1 || Number(attrs.rowspan ?? 1) > 1) return true
      const cellContent = cell.content ?? []
      return cellContent.length > 1 || cellContent.some((c) => c.type !== MarkupNodeType.paragraph)
    })
  )

  if (isComplex) {
    state.write(state.renderHtml(node))
    state.closeBlock(node)
    return
  }

  // Render GFM Pipe Table
  const tableMatrix: string[][] = []
  let hasHeader = false

  for (let r = 0; r < rows.length; r++) {
    const row = rows[r]
    const cells = row.content ?? []
    const rowCells: string[] = []
    for (const cell of cells) {
      if (cell.type === MarkupNodeType.table_header) hasHeader = true
      // Extract text content and escape pipes
      const cellText = extractInlineText(cell).replace(/\|/g, '\\|').trim()
      rowCells.push(cellText)
    }
    tableMatrix.push(rowCells)
  }

  if (tableMatrix.length === 0) return

  // Format header and separator
  const colCount = Math.max(...tableMatrix.map((r) => r.length))
  const headerRow = tableMatrix[0]

  state.write('| ' + headerRow.map((c, i) => c || `Col ${i + 1}`).join(' | ') + ' |\n')
  state.write('| ' + Array(colCount).fill('---').join(' | ') + ' |\n')

  for (let r = hasHeader ? 1 : 0; r < tableMatrix.length; r++) {
    const row = tableMatrix[r]
    const padded = Array.from({ length: colCount }, (_, i) => row[i] ?? '')
    state.write('| ' + padded.join(' | ') + ' |\n')
  }
  state.ensureNewLine()
  state.closeBlock(node)
}
```

### 5.2 Handling Images

An `image` node in Huly AST contains:
```json
{
  "type": "image",
  "attrs": {
    "file-id": "674a2b9c...",
    "alt": "architecture-diagram.png",
    "width": 800
  }
}
```

Depending on the export mode, image URLs must be resolved accordingly:
1. **Direct Web Download (Standalone `.md`)**:
   Resolve image paths to public/presigned Huly file storage URLs using `getFileUrl(fileId, alt)`.
   Output: `![architecture-diagram.png](https://huly.app/files/workspaceId/674a2b9c...)`
2. **Asset Bundle Export (`.zip`)**:
   Download all image blobs, save them inside an `assets/` subfolder, and rewrite Markdown references to relative paths:
   Output: `![architecture-diagram.png](./assets/architecture-diagram.png)`
3. **Self-Contained Markdown**:
   Optionally convert images to embedded Data URIs:
   Output: `![diagram](data:image/png;base64,iVBORw0KGgo...)`

### 5.3 Embedded Attachments (`file` node type)

In Huly's collaborative editor, files attached directly in text have `type: MarkupNodeType.file` with attributes `file-id`, `data-file-name`, `data-file-size`, and `data-file-type`.

The current `storeNodes` in `serializer.ts` does not contain a handler for `file`. Adding the following handler provides seamless attachment representation:

```typescript
file: (state, node) => {
  const attrs = nodeAttrs(node)
  const name = attrs['data-file-name'] ?? attrs.name ?? 'attachment'
  const fileId = attrs['file-id'] ?? ''
  const size = attrs['data-file-size'] ? ` (${humanReadableFileSize(Number(attrs['data-file-size']))})` : ''
  const url = state.options.fileUrlResolver
    ? state.options.fileUrlResolver(fileId, String(name))
    : `${state.imageUrl}${fileId}`

  state.write(`[📎 ${state.esc(String(name))}${size}](${url})\n`)
  state.closeBlock(node)
}
```

### 5.4 Code Blocks & Mermaid Diagrams

Huly supports syntax-highlighted code blocks and interactive Mermaid diagrams:
- `codeBlock`: Serialized with triple backticks and language specifier (```` ```typescript ````).
- `mermaid`: Serialized with language `mermaid`:
  ````markdown
  ```mermaid
  graph TD;
    A-->B;
    A-->C;
  ```
  ````
  This is fully supported in `foundations/core/packages/text-markdown/src/serializer.ts` line 106.

### 5.5 Task Lists & Checkboxes

Huly documents support interactive todo items (`todoList` / `todoItem`):
- `todoList` node contains `todoItem` children with attributes `checked: boolean`, `todoid: string`, and `userid: string`.
- Serialized as:
  ```markdown
  * [x] Completed task <!-- todoid=...,userid=... -->
  * [ ] Pending task
  ```
  The HTML comment preserves Huly task IDs for two-way synchronization while remaining clean when rendered in standard Markdown previewers.

### 5.6 Internal References & Backlinks

Mentioning other documents, issues, or users produces a `reference` node (`_class`, `id`, `label`):
- Serialized as:
  ```markdown
  [@HULY-102: Add Markdown Export](ref://?_class=tracker%3Aclass%3AIssue&_id=674...&label=HULY-102)
  ```
- For clean export, the `refUrlResolver` can format this as a standard markdown link to the document web URL or readable title:
  ```markdown
  [HULY-102: Add Markdown Export](https://huly.app/workspace/tracker/HULY-102)
  ```

---

## 6. Exact Code Changes & Implementation Plan

### 6.1 Plugin Contract (`plugins/document/src/plugin.ts`)

Declare the new action and string identifiers:

```typescript
export const documentPlugin = plugin(documentId, {
  // ... existing declarations ...
  action: {
    CreateChildDocument: '' as Ref<Action>,
    CreateDocument: '' as Ref<Action>,
    EditTeamspace: '' as Ref<Action>,
    ExportMarkdown: '' as Ref<Action>,       // <-- NEW
    ExportTreeMarkdown: '' as Ref<Action>,   // <-- NEW
    CopyMarkdown: '' as Ref<Action>          // <-- NEW
  },
  string: {
    // ... existing strings ...
    ExportToMarkdown: '' as IntlString,      // <-- NEW
    ExportTreeToMarkdown: '' as IntlString,  // <-- NEW
    CopyAsMarkdown: '' as IntlString,        // <-- NEW
    MarkdownCopied: '' as IntlString         // <-- NEW
  }
})
```

### 6.2 Localization Strings (`plugins/document-assets/lang/en.json`)

```json
{
  "ExportToMarkdown": "Export to Markdown",
  "ExportTreeToMarkdown": "Export Document Tree (.zip)",
  "CopyAsMarkdown": "Copy as Markdown",
  "MarkdownCopied": "Markdown copied to clipboard"
}
```

### 6.3 Model Action Registration (`models/document/src/index.ts`)

Register the actions on `document.class.Document` inside `defineDocument(builder)`:

```typescript
// Export to Markdown action
createAction(
  builder,
  {
    action: document.actionImpl.ExportMarkdown,
    label: document.string.ExportToMarkdown,
    icon: view.icon.Download,
    input: 'focus',
    category: document.category.Document,
    target: document.class.Document,
    context: {
      mode: ['context', 'browser'],
      application: document.app.Documents,
      group: 'tools'
    }
  },
  document.action.ExportMarkdown
)

// Copy as Markdown action
createAction(
  builder,
  {
    action: document.actionImpl.CopyMarkdown,
    label: document.string.CopyAsMarkdown,
    icon: view.icon.CopyId,
    input: 'focus',
    category: document.category.Document,
    target: document.class.Document,
    context: {
      mode: ['context', 'browser'],
      application: document.app.Documents,
      group: 'copy'
    }
  },
  document.action.CopyMarkdown
)
```

### 6.4 Enhancing the Serializer (`foundations/core/packages/text-markdown/src/serializer.ts`)

1. **Add `file` node handler**:
```typescript
storeNodes.file = (state, node) => {
  const attrs = nodeAttrs(node)
  const name = attrs['data-file-name'] ?? attrs.name ?? 'attachment'
  const fileId = attrs['file-id'] ?? ''
  const size = attrs['data-file-size'] ? ` (${humanReadableFileSize(Number(attrs['data-file-size']))})` : ''
  const url = `${state.imageUrl}${fileId}`
  state.write(`[📎 ${state.esc(String(name))}${size}](${url})\n`)
  state.closeBlock(node)
}
```

2. **Add options for URL resolution**:
```typescript
export interface StateOptions {
  tightLists: boolean
  refUrl: string
  imageUrl: string
  htmlWriter?: HtmlWriter
  fileUrlResolver?: (fileId: string, filename?: string) => string
  refUrlResolver?: (attrs: Record<string, any>) => string
}
```

### 6.5 Action Implementation (`plugins/document-resources/src/actions/exportMarkdown.ts`)

Create the export logic with frontmatter and asset resolution:

```typescript
import { type Document } from '@hcengineering/document'
import { getClient, getFileUrl, getMarkup, copyTextToClipboard } from '@hcengineering/presentation'
import { markupToJSON } from '@hcengineering/text'
import { markupToMarkdown } from '@hcengineering/text-markdown'
import { makeDocCollabId } from '@hcengineering/core'
import { addNotification, NotificationSeverity } from '@hcengineering/ui'

export interface ExportMarkdownOptions {
  includeFrontmatter?: boolean
  resolveAssetUrls?: boolean
}

function generateFrontmatter(doc: Document): string {
  const lines: string[] = ['---']
  lines.push(`title: "${doc.title.replace(/"/g, '\\"')}"`)
  lines.push(`id: "${doc._id}"`)
  if (doc.space) lines.push(`space: "${doc.space}"`)
  if (doc.createdOn) lines.push(`createdOn: "${new Date(doc.createdOn).toISOString()}"`)
  if (doc.modifiedOn) lines.push(`modifiedOn: "${new Date(doc.modifiedOn).toISOString()}"`)
  lines.push('---\n\n')
  return lines.join('\n')
}

export async function exportDocumentMarkdown(
  doc: Document,
  options: ExportMarkdownOptions = { includeFrontmatter: true, resolveAssetUrls: true }
): Promise<void> {
  let markdownBody = ''

  if (doc.content != null) {
    const collabId = makeDocCollabId(doc, 'content')
    const markupStr = await getMarkup(collabId, doc.content)
    if (markupStr) {
      const ast = markupToJSON(markupStr)
      markdownBody = markupToMarkdown(ast, {
        imageUrl: '',
        refUrl: ''
      })
    }
  }

  const frontmatter = options.includeFrontmatter ? generateFrontmatter(doc) : ''
  const fullMarkdown = `${frontmatter}# ${doc.title}\n\n${markdownBody}`

  // Browser download
  const blob = new Blob([fullMarkdown], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${sanitizeFilename(doc.title || 'document')}.md`
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  URL.revokeObjectURL(url)
  document.body.removeChild(a)
}

export async function copyDocumentMarkdown(doc: Document): Promise<void> {
  let markdownBody = ''
  if (doc.content != null) {
    const collabId = makeDocCollabId(doc, 'content')
    const markupStr = await getMarkup(collabId, doc.content)
    if (markupStr) {
      const ast = markupToJSON(markupStr)
      markdownBody = markupToMarkdown(ast)
    }
  }
  const fullMarkdown = `# ${doc.title}\n\n${markdownBody}`
  await copyTextToClipboard(fullMarkdown)
  addNotification('Copied', 'Document copied as Markdown to clipboard', undefined, undefined, NotificationSeverity.Info)
}

function sanitizeFilename(name: string): string {
  return name.replace(/[/\\?%*:|"<>]/g, '-').trim()
}
```

### 6.6 Wiring Resources (`plugins/document-resources/src/index.ts`)

Export the actions in the default resource factory:

```typescript
import { exportDocumentMarkdown, copyDocumentMarkdown } from './actions/exportMarkdown'

export default async (): Promise<Resources> => ({
  // ... existing components ...
  actionImpl: {
    CreateChildDocument: createChildDocument,
    CreateDocument: createDocument,
    EditTeamspace: editTeamspace,
    LockContent: lockContent,
    UnlockContent: unlockContent,
    ExportMarkdown: exportDocumentMarkdown,  // <-- Registered
    CopyMarkdown: copyDocumentMarkdown       // <-- Registered
  },
  // ... existing functions ...
})
```

---

## 7. Hierarchical / Folder Tree Export (Multi-Document Archive)

In Huly, documents form a tree hierarchy (`parent` -> child documents). When a user exports a knowledge base space or a parent document with nested pages, they expect a directory structure:

```
Engineering-Wiki.zip
├── README.md                          # Parent document content
├── Architecture/
│   ├── README.md                      # "Architecture" document content
│   ├── Microservices.md               # Child document
│   └── Database-Design.md             # Child document
└── assets/
    ├── diagram-1.png                  # Embedded images from documents
    └── schema.pdf
```

### Tree Export Implementation Pattern:
1. Using `LiveQuery` or `client.findAll(document.class.Document, { space: activeSpaceId })`, fetch all descendant documents.
2. Construct a map of `parent -> children[]`.
3. Recursively serialize each document into a `JSZip` folder hierarchy.
4. For any `image` or `file` nodes in the AST:
   - Fetch the raw binary blob via `fetch(getFileUrl(fileId))`.
   - Store in `assets/${fileId}.${ext}` inside the zip.
   - Update Markdown link to relative path `./assets/${fileId}.${ext}`.
5. Generate the ZIP buffer (`zip.generateAsync({ type: 'blob' })`) and trigger download of `${spaceName}.zip`.

---

## 8. Verification & Manual Testing Checklist

Following project instructions, verification should be performed manually:

1. **Document Action Availability**:
   - Open any existing document in Huly.
   - Click the `...` ("More actions") button in the document header title bar. Verify that **"Export to Markdown"** and **"Copy as Markdown"** appear in the dropdown menu.
   - Right-click any document item in the left-hand Navigator tree. Verify that **"Export to Markdown"** appears in the context menu.
2. **Content Fidelity Verification**:
   - Create a document containing:
     - Headings (H1, H2, H3).
     - Bold, italic, strikethrough, inline code, and colored text.
     - Blockquotes and multi-level bulleted / numbered lists.
     - Todo items with checkboxes.
     - Code block with language specification and a Mermaid diagram.
     - An uploaded inline image and an attached file.
     - A 3x3 table with headers.
   - Click "Export to Markdown". Verify the downloaded file name matches `${doc.title}.md`.
   - Open the `.md` file in VS Code or Obsidian. Verify all formatting renders accurately.
3. **Collaborative Live Keystroke Test**:
   - In one browser window, edit a document without waiting for the 10-second debounce flush.
   - Trigger "Export to Markdown" immediately. Verify the exported file includes the latest edits.
4. **Copy as Markdown Test**:
   - Trigger "Copy as Markdown". Paste into an external text editor. Verify valid Markdown clipboard output.
