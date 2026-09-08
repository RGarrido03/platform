# Huly Platform Core Architecture & Extension Mechanisms

Comprehensive architectural research report providing the foundational platform analysis for feature engineering tasks (multi-screen sharing, video resolution increase, markdown document export, and external test management ingestion).

---

## 1. Microservices Topology & Communication Patterns

Huly is an open-source collaborative platform structured around a distributed microservices topology designed for real-time reactivity, multi-tenant workspace isolation, and high concurrency.

```
                                 +-------------------------+
                                 |  Web Browser / Desktop  |
                                 +------------+------------+
                                              |
                        +---------------------+---------------------+
                        | (HTTP :8087)                              | (WS :3332 / :3078 / :8099)
                        v                                           |
                 +--------------+                                   |
                 | Front Server |                                   |
                 +-------+------+                                   |
                         | /config.json                             |
                         v                                          |
+-------------------------------------------------------------+     |
|                       CORE SERVICES                         |     |
|                                                             |     |
|  +-------------------+              +--------------------+  |<----+
|  |  Account Service  |              |     Transactor     |  |
|  |      (:3000)      |              |      (:3332)       |  |
|  +---------+---------+              +---------+----------+  |
|            |                                  |             |
|            |                                  | Tx Pipeline |
|            v                                  v             |
|  +-------------------------------------------------------+  |
|  |             CockroachDB (Primary Database)            |  |
|  |            (:26257 distributed SQL / JSONB)           |  |
|  +-------------------------------------------------------+  |
+-------------------------------------------------------------+
            |                                  |
            | Events                           | Storage
            v                                  v
+-------------------------+        +--------------------------+
|  Redpanda / Kafka :9092 |        |     MinIO (S3 API :9000) |
|  Topic-based messaging  |        |     Buckets: blobs, eu   |
+------------+------------+        +-------------+------------+
             |                                   |
             | Consumers                         | Files & Blobs
             v                                   v
+-------------------------+        +--------------------------+
| - Fulltext (:4702/9200) |        | - Datalake (:4030)       |
| - Rekoni (:4004)        |        | - Hulylake (:8096)       |
| - Media Processing      |        | - Collaborator (:3078)   |
| - HulyGun / Process     |        | - Stream (:1080)         |
+-------------------------+        +--------------------------+
```

### 1.1 Microservices Inventory

1. **Core Business & Data Layer**:
   - **Transactor (`pods/server`, port 3332)**: The authoritative engine for all data mutations and queries. Maintains stateful client WebSocket sessions, validates permissions, processes transactions through a 26-step middleware pipeline, persists state to CockroachDB, emits events to Redpanda, and broadcasts updates back to subscribed clients. Also exposes an HTTP REST RPC API (`/api/v1/*`).
   - **Account Service (`server/account`, `server/account-service`, port 3000)**: Handles identity, authentication (email/password, social logins, OTP), workspace discovery, membership roles, and issuance/revocation of JWTs and revokable API tokens.
   - **Workspace Service (`server/workspace-service`)**: Manages workspace lifecycle (creation, initialization, schema upgrades, migration).
   - **Stats Service (`pods/stats`, port 4900)**: Collects operational metrics, active user stats, and performance telemetry.

2. **Data & Storage Services**:
   - **CockroachDB (ports 26257, 8089)**: Primary distributed SQL database with ACID transactional guarantees. Replaces MongoDB in modern Huly deployments. Stores all workspace domain data, transactions, user metadata, and accounts.
   - **Datalake (`foundations/server/packages/datalake`, `services/datalake`, port 4030)**: Object storage management service with metadata tracking and permission verification.
   - **Hulylake (`foundations/server/packages/hulylake`, port 8096)**: High-performance S3-compatible storage adapter for binary data and attachment streams.
   - **MinIO (ports 9000, 9001)**: S3-compatible backend storage containing buckets (`blobs`, `eu`, `backups`).

3. **Real-Time Collaboration & Notification Services**:
   - **Collaborator (`server/collaborator`, `pods/collaborator`, port 3078)**: Built on top of `@hocuspocus/server`. Manages real-time rich-text collaboration for documents, task descriptions, and meeting notes using Y.js CRDTs. Synchronizes with CockroachDB/MinIO storage.
   - **HulyPulse (`foundations/hulypulse`, port 8099)**: Redis-backed WebSocket server for real-time notification pushes.
   - **Redpanda (ports 9092, 19092)**: High-throughput Kafka-compatible event streaming bus connecting asynchronous producers (Transactor, Workspace) to consumers (Fulltext, Media, Process).

4. **Media & Meetings Layer**:
   - **Love Service (`services/love`, port 4030/custom)**: Meeting orchestration service interfacing with LiveKit. Handles LiveKit room lifecycle, authentication tokens, participant states, recording egress (via LiveKit EgressClient), and transcoded stream archival.
   - **LiveKit Server (external/docker)**: WebRTC SFU (Selective Forwarding Unit) handling real-time audio, video, and screen sharing streams.
   - **Stream Service (`foundations/stream`, port 1080)**: Transcodes recorded meetings and provides HLS streaming endpoints.
   - **Preview Service (`services/preview`, port 4040)**: Generates image thumbnails and document previews.

5. **Search & Intelligence**:
   - **Fulltext (`server/indexer`, port 4702)**: Consumes transaction events from Redpanda, indexes content into Elasticsearch (`:9200`).
   - **Rekoni (`packages/rekoni`, `services/rekoni`, port 4004)**: Document intelligence service extracting structured content from binary formats (PDF, DOCX, resumes).

### 1.2 Database Architecture in CockroachDB

CockroachDB storage is implemented in `@hcengineering/postgres` (`foundations/server/packages/postgres`). Rather than mapping individual TypeScript classes to individual SQL tables, Huly partitions data by **Storage Domains**:

```sql
CREATE TABLE IF NOT EXISTS ${domain} (
  "workspaceId" uuid NOT NULL,
  ${indexed_columns},
  data JSONB NOT NULL,
  PRIMARY KEY ("workspaceId", _id)
);
```

- **Domain Tables**:
  - `tx`: Immutable record of every committed transaction (`TxCreateDoc`, `TxUpdateDoc`, etc.).
  - `default`: General workspace entities (tasks, issues, projects, test runs, test suites).
  - `space`: Workspace spaces, teamspaces, projects, and permissions.
  - `collaborator`: Document synchronization state and Y.js snapshots.
  - `notification`, `relation`, `calendar`, `time`: Dedicated tables optimized for specific query patterns.
- **Data Structure**:
  - Top-level indexed columns (`_id`, `_class`, `space`, `modifiedBy`, `modifiedOn`, `attachedTo`, etc.) carry BTree or GIN indexes for fast relational querying.
  - The remaining entity-specific payload is stored in the `data JSONB` column.
  - Primary key is compound: `("workspaceId", _id)`, providing multi-tenant isolation and locality.

---

## 2. Data Modeling & Transaction Mutation Flow

### 2.1 Data Modeling Conventions

All entities in Huly derive from base platform primitives in `@hcengineering/core`:

1. **Document (`Doc`)**:
   ```typescript
   interface Doc {
     _id: Ref<Doc>          // 24-character hexadecimal unique identifier
     _class: Ref<Class<Doc>> // Global PRI reference to entity class definition
     space: Ref<Space>      // Workspace space or project partition
     modifiedBy: PersonId   // Actor who made the last change
     modifiedOn: Timestamp  // Unix timestamp (ms)
     createdBy?: PersonId
     createdOn?: Timestamp
   }
   ```
2. **Attached Document (`AttachedDoc`)**:
   Entities that do not exist standalone in the root space, but are embedded inside a collection of a parent document:
   ```typescript
   interface AttachedDoc extends Doc {
     attachedTo: Ref<Doc>           // Parent entity _id
     attachedToClass: Ref<Class<Doc>> // Parent entity class
     collection: string             // Collection name on parent (e.g. 'testCases', 'results')
   }
   ```
3. **Mixins (`Mixin<M>`)**:
   Dynamic aspect extensions attached to existing documents without altering base table schemas (e.g., `Employee`, `DefaultProjectTypeData`).

4. **Entity Definition Pattern**:
   Models are declared with TypeScript decorators in `models/<name>`:
   ```typescript
   @Model(testManagement.class.TestSuite, core.class.Doc, DOMAIN_TEST_MANAGEMENT)
   @UX(testManagement.string.TestSuite, testManagement.icon.TestSuite)
   export class TTestSuite extends TDoc implements TestSuite {
     @Prop(TypeString(), testManagement.string.SuiteName)
     @Index(IndexKind.FullText)
     name!: string

     @Prop(TypeRef(testManagement.class.TestSuite), testManagement.string.TestSuite)
     parent!: Ref<TestSuite>

     @Prop(Collection(testManagement.class.TestCase), testManagement.string.TestCases)
     testCases?: CollectionSize<TestCase>
   }
   ```

5. **ID Generation**:
   All Huly IDs are 24-character lowercase hex strings (`^[0-9a-f]{24}$`), generated via `generateId()` (`timestamp(8) + random(10) + counter(6)`).

### 2.2 The Object Mutation Flow (Transactor Pipeline)

Mutations are never executed as direct SQL `INSERT`/`UPDATE` calls from clients. Instead, every change is submitted as a typed **Transaction (`Tx`)** processed by the Transactor's middleware pipeline (`server/server-pipeline/src/pipeline.ts`).

#### The 26-Step Pipeline Execution Chain:
1. **`LookupMiddleware`**: Pre-populates foreign references and relation lookups.
2. **`NormalizeTxMiddleware`**: Normalizes transaction shapes and standardizes payload keys.
3. **`IdentityMiddleware`**: Validates client identity, authenticated user token, and session ownership.
4. **`ModifiedMiddleware`**: Automatically injects `modifiedBy`, `modifiedOn`, `createdBy`, `createdOn`.
5. **`RankMiddleware`**: Automatically calculates fractional indexing / LexoRank ordering for sortable entities.
6. **`FindSecurityMiddleware`**: Evaluates read permissions for search/query operations.
7. **`PluginConfigurationMiddleware`**: Evaluates plugin-specific configuration rules.
8. **`PrivateMiddleware`**: Filters documents marked as private to specific users.
9. **`SpaceSecurityMiddleware` / `SpacePermissionsMiddleware` / `GuestPermissionsMiddleware`**: Enforces workspace role-based access control (Admin, Member, Guest) and space membership.
10. **`ConfigurationMiddleware` / `ContextNameMiddleware` / `MarkDerivedEntryMiddleware`**: Injects execution context and derives metadata.
11. **`CommunicationMiddleware`**: Routes events to communication APIs (chats, comments, threads).
12. **`UserStatusMiddleware`**: Updates actor active/presence status.
13. **`ApplyTxMiddleware`**: Evaluates atomic conditional operations (`TxApplyIf`) with `match` and `notMatch` assertions.
14. **`VersioningMiddleware` / `IdentifierMiddleware`**: Manages entity version numbers and auto-incrementing identifiers (e.g., `HULY-101`).
15. **`RatingMiddleware`**: Enforces content rating constraints.
16. **`TxMiddleware`**: Prepares the transaction record itself to be stored in the `tx` domain.
17. **`TriggersMiddleware`**: Invokes registered server plugin triggers (`OnStateUpdate`, etc.). Triggers receive the pending transaction batch and can return new derived transactions to be executed in the exact same atomic commit.
18. **`FullTextMiddleware`**: Emits index payloads to Elasticsearch for full-text searchability.
19. **`LowLevelMiddleware` / `TxOrderingMiddleware`**: Guarantees linear transaction ordering and concurrency control per workspace.
20. **`QueryJoinMiddleware` / `LiveQueryMiddleware`**: Coordinates active subscriptions and query cache invalidations.
21. **`DomainFindMiddleware` / `DomainTxMiddleware`**: Routes the transaction to the target storage adapter according to class domain mapping.
22. **`QueueMiddleware`**: Asynchronously publishes transaction events to Redpanda (Kafka topic) for downstream background workers.
23. **`DBAdapterInitMiddleware`**: Verifies database connection readiness.
24. **`ModelMiddleware`**: Validates schema compliance against in-memory `ModelDb`.
25. **`DBAdapterMiddleware`**: Translates the transaction into SQL operations and commits it to CockroachDB.
26. **`BroadcastMiddleware`**: Broadcasts the committed transaction batch to all active WebSocket sessions connected to the workspace.

#### Transaction Types (`TxCUD`):
- **`TxCreateDoc`**: Creates a new document.
- **`TxUpdateDoc`**: Updates an existing document using MongoDB-style operators (`$set`, `$unset`, `$push`, `$pull`, `$inc`).
- **`TxRemoveDoc`**: Soft- or hard-deletes a document.
- **`TxCollectionCUD`**: Wraps a `TxCreateDoc`, `TxUpdateDoc`, or `TxRemoveDoc` targeting an `AttachedDoc` inside a collection (`attachedTo`, `attachedToClass`, `collection`).
- **`TxMixin`**: Updates mixin attributes on an existing document.
- **`TxApplyIf`**: Transaction batch guarded by preconditions.

---

## 3. Client Architecture & Plugin Framework

### 3.1 Plugin System Architecture

Huly's frontend is completely modular, built with Svelte and governed by `@hcengineering/platform`. Plugins are separated into four distinct packages:

| Monorepo Path | Role | Description |
|---|---|---|
| `plugins/<name>` | Contract | Declares the plugin ID, class references, PRI constants, icons, strings, and extension points. Lightweight, zero implementation code. |
| `plugins/<name>-assets` | Static Assets | SVGs, branding images, and raw static resources. |
| `plugins/<name>-resources` | Implementation | Svelte components, action handlers, completion providers, and location resolvers. Dynamically loaded on demand via `addLocation()`. |
| `server-plugins/<name>` & `-resources` | Server Logic | Server-side triggers, HTML/text formatters, and backend mutation handlers executed by the Transactor. |

#### Platform Resource Identifiers (PRI):
Resources are decoupled from their implementations using PRIs:
```typescript
// Defined in plugins/document/src/plugin.ts
export const documentPlugin = plugin('document' as Plugin, {
  class: { Document: '' as Ref<Class<Document>> },
  component: { CreateDocument: '' as AnyComponent },
  action: { CreateDocument: '' as Ref<Action> }
})

// Implemented in plugins/document-resources/src/index.ts
export default async (): Promise<Resources> => ({
  component: { CreateDocument },
  actionImpl: { CreateDocument: createDocument }
})
```

### 3.2 Workspace & Session Initialization

1. **Discovery & Login**:
   - The client fetches `/config.json` from the front server to discover `ACCOUNTS_URL`, `COLLABORATOR_URL`, and `FILES_URL`.
   - The user authenticates with `AccountClient` (`POST /api/v1/auth/login`).
   - The user selects a workspace (`accountClient.selectWorkspace(workspaceUuid)`), receiving a workspace-scoped JWT token and the target Transactor endpoint.

2. **Transactor WebSocket Handshake**:
   - The client opens a WebSocket connection directly to the Transactor:
     ```
     ws://<transactor-host>:3332/<workspace-token>?sessionId=<client-generated-uuid>
     ```
   - Handshake sequence:
     - Client opens connection.
     - Server decodes token, registers session in `SessionManager`, and responds with an initial system handshake message:
       ```json
       { "id": -1, "result": "hello", "serverVersion": "0.7.0", "lastTx": "...", "account": { ... } }
       ```
     - Client loads workspace classes and model hierarchy (`loadModel`).

3. **Reactivity & Data Access (`LiveQuery`)**:
   - UI components retrieve the active client with `getClient()` from `@hcengineering/presentation` (which implements `TxOperations & Client`).
   - To query data reactively, Svelte components call `createQuery()`:
     ```typescript
     import { createQuery, getClient } from '@hcengineering/presentation'
     const query = createQuery()
     $: docs = query.findAll(document.class.Document, { space: activeSpaceId })
     ```
   - When any client executes a mutation, the Transactor processes the transaction and broadcasts the result over WebSocket to all workspace sessions (`{ id: -2, result: [txArray] }`).
   - The client's WebSocket listener ingests the transactions, updates its local cache, and notifies `LiveQuery`, causing affected Svelte components to re-render reactively without full-page reloads.

---

## 4. Authentication, Session Tokens & External Integration

### 4.1 Token Structure & Security

All service-to-service and client-to-server communication relies on signed JWTs generated via `@hcengineering/server-token`:

```typescript
interface Token {
  account: AccountUuid      // User UUID in account service
  workspace: WorkspaceUuid  // Workspace UUID
  extra?: {
    apiTokenId?: string     // Present if this is a personal access / API token
    service?: string        // Present if generated by internal service (e.g. 'transactor')
    admin?: 'true'          // Administrative override
    mode?: string
    model?: string
  }
  grant?: PermissionsGrant  // Explicit role and space grants
  exp?: number              // Expiration timestamp (seconds since epoch)
  nbf?: number              // Not before timestamp
}
```

- **Signing Secret**: Signed with `SERVER_SECRET` (configured via env, default `'secret'`). All microservices share this secret for zero-latency internal signature verification.
- **Revocation Resolution**:
  - Regular session tokens expire naturally via `exp`.
  - API Tokens carry `extra.apiTokenId`. When Transactor encounters `apiTokenId`, it executes `verifyToken()`, which delegates to `apiTokenRevocationChecker`.
  - The check queries the Account service (`getLoginInfoByToken()`).
  - Results are cached in a bounded memory cache (`REVOCATION_CACHE_TTL_MS = 60,000`, max 4096 entries) to protect Account service throughput while ensuring rapid revocation enforcement.

### 4.2 API Tokens (Personal Access Tokens)

Huly has built-in support for persistent, revokable API tokens in Account Service (`server/account/src/operations.ts`):
- Created via `accountClient.createApiToken(name, workspaceUuid, days)`.
- Stored in CockroachDB table `api_tokens` (`accountUuid`, `workspaceUuid`, `name`, `expiresOn`, `revoked`).
- Can be passed directly in the HTTP header: `Authorization: Bearer <apiToken>`.

### 4.3 Transactor REST RPC API (External Ingestion & Querying)

External services and automated tools do not need to maintain complex WebSocket state. The Transactor natively exposes an HTTP REST RPC API on port 3332 (`pods/server/src/rpc.ts`):

| Endpoint | Method | Purpose | Payload / Parameters |
|---|---|---|---|
| `/api/v1/ping/:workspaceId` | `GET` | Health check & last transaction status | Returns `{ pong: true, lastTx, lastHash }` |
| `/api/v1/find-all/:workspaceId` | `GET` / `POST` | Query documents by class & criteria | `{ "_class": "...", "query": { ... }, "options": { "limit": 100 } }` |
| `/api/v1/tx/:workspaceId` | `POST` | Execute atomic mutation transactions | `{ "_class": "core:class:TxCreateDoc", ... }` or `TxCollectionCUD` |
| `/api/v1/generate-id/:workspaceId` | `GET` | Generate valid 24-char hex IDs | Returns `{ "id": "673abc..." }` |
| `/api/v1/load-model/:workspaceId` | `GET` | Download model schema & hierarchy | Query params `full=true` |
| `/api/v1/account/:workspaceId` | `GET` | Fetch authenticated account details | Account UUID, social IDs, profile info |
| `/api/v1/ensure-person/:workspaceId` | `POST` | Ensure Person entity exists for social ID | `{ socialType, socialValue, firstName, lastName }` |

All REST RPC endpoints accept `Authorization: Bearer <token>` (where token is either a workspace session token or an API token).

### 4.4 Official Client SDKs

- **Node.js / TypeScript**: `@hcengineering/api-client`
  ```typescript
  import { connectRest, createRestTxOperations } from '@hcengineering/api-client'
  
  // Option 1: High-level client connection
  const client = await connectRest('http://localhost:8087', {
    email: 'user@example.com',
    password: 'password',
    workspace: 'my-workspace'
  })
  
  // Option 2: Pre-generated API Token
  const txOps = await createRestTxOperations(
    'http://localhost:3332',
    workspaceId,
    apiToken
  )
  await txOps.createDoc(myClass, mySpace, { name: 'Test' })
  ```
- **Python / External HTTP Clients**:
  Because Transactor endpoints use standard JSON over HTTP (`POST /api/v1/tx/:workspaceId`), any language (Python, Go, Rust, cURL) can submit transactions directly by formatting standard `TxCreateDoc` or `TxCollectionCUD` JSON payloads with an `Authorization: Bearer <apiToken>` header.

---

## 5. Architectural Guidance for Feature Tasks

### 5.1 Meeting Multi-Screen Sharing (Task t2)
- **LiveKit Client Integration**: `plugins/love-resources/src/liveKitClient.ts` manages room connection, audio/video/screen tracks.
- **Current Single-Share Restriction**: `ScreenSharingView.svelte` and `ParticipantView.svelte` assume a single presenter layout. In LiveKit, multiple participants (or one participant with multiple displays) can publish `Track.Source.ScreenShare` simultaneously.
- **Required Changes**:
  1. Update `plugins/love-resources/src/stores.ts` to maintain a reactive list/map of all active screen-share tracks rather than a single active screen track.
  2. Modify `ScreenSharingView.svelte` to support multi-track grid/carousel rendering with presenter selection tabs.
  3. Ensure room audio/video publishing constraints in `liveKitClient.ts` do not unpublish or unbind existing tracks when a second track is published.

### 5.2 Meeting Video Resolution & Quality (Task t3)
- **Client Encoding Presets**: Located in `plugins/love-resources/src/liveKitClient.ts` (`screenShareEncoding`, `videoCaptureDefaults`).
- **Server Egress & Recording Presets**: Located in `services/love/src/preset.ts` (`EncodingOptionsPreset`, `getRecordingPreset`).
- **Required Changes**:
  1. Expand client video capture presets from standard 720p to include 1080p (Full HD) and 4K (for presentations/screen sharing).
  2. Implement Simulcast and Dynacast configurations in `liveKitClient.ts` to allow high-resolution publishing without degrading mobile or low-bandwidth viewers.
  3. Add UI quality selection in `plugins/love-resources/src/components/meeting/CamSettingPopup.svelte` and `ShareSettingPopup.svelte`.
  4. Ensure Docker LiveKit server limits (`livekit.yaml`) allow appropriate bitrates (up to 3-6 Mbps for 1080p/4K).

### 5.3 Exporting Documents to Markdown (Task t4)
- **Document Data Representation**:
  - Collaborative document content is edited in Y.js (`collaborator` / `@hocuspocus/server`) and saved as `Markup` in entity attributes or MinIO blobs (`models/document`, `plugins/document`).
- **Existing Built-In Libraries**:
  - `@hcengineering/text-markdown`: Already provides `markupToMarkdown(markup: MarkupNode, options?): string` and `markdownToMarkup(markdown: string): string`!
  - `@hcengineering/text-ydoc`: Provides `yDocToMarkup(ydoc: YDoc, field: string): Markup`!
  - `@hcengineering/text`: Provides `markupToJSON(markup: Markup): MarkupNode`!
- **Architectural Flow**:
  - **Client-Side Export**:
    1. Read active document `Markup` from client cache or fetch active Y.Doc from Collaborator.
    2. Convert: `yDocToMarkup(ydoc, 'content')` -> `markupToJSON(markup)` -> `markupToMarkdown(markupNode)`.
    3. Trigger browser download of `.md` file in `plugins/document-resources` via Document Action menu (`actionImpl.ExportMarkdown`).
  - **Asset Handling**: Resolve `image://<blobId>` URIs to workspace file download URLs (`/blob/:workspace/:blobId/:filename`).

### 5.4 Test Management External Ingestion & `pytest-huly` (Task t5)
- **Domain Model Structure (`models/test-management/src/types.ts`)**:
  - `TestProject`: Root space (extends `TypedSpace`).
  - `TestSuite`: Standalone entity (extends `Doc`, space = `TestProject`).
  - `TestCase`: Attached entity (extends `AttachedDoc`, `attachedTo: TestSuite._id`, collection = `'testCases'`).
  - `TestRun`: Standalone entity (extends `Doc`, space = `TestProject`).
  - `TestResult`: Attached entity (extends `AttachedDoc`, `attachedTo: TestRun._id`, collection = `'results'`, references `testCase`).
- **Mutation Pattern for Pytest Ingestion**:
  1. External ingestion service or Python client obtains an API Token and generates 24-character hex IDs.
  2. Creates `TestRun` via `TxCreateDoc`:
     ```json
     {
       "_id": "<txId>",
       "_class": "core:class:TxCreateDoc",
       "objectClass": "test-management:class:TestRun",
       "objectId": "<testRunId>",
       "objectSpace": "<testProjectId>",
       "attributes": { "name": "CI Run #42", "dueDate": 1788658000000 }
     }
     ```
  3. Appends test results via `TxCollectionCUD`:
     ```json
     {
       "_id": "<txId2>",
       "_class": "core:class:TxCreateDoc",
       "objectClass": "test-management:class:TestResult",
       "objectId": "<resultId>",
       "objectSpace": "<testProjectId>",
       "attachedTo": "<testRunId>",
       "attachedToClass": "test-management:class:TestRun",
       "collection": "results",
       "attributes": {
         "name": "test_payment_flow",
         "testCase": "<testCaseId>",
         "status": "<passedStatusRef>"
       }
     }
     ```
  4. Posts payload directly to `POST /api/v1/tx/:workspaceId`.
- **Python Package (`pytest-huly`) Architecture**:
  - Hooks: `pytest_sessionstart` (creates TestRun), `pytest_runtest_makereport` (collects individual outcomes), `pytest_sessionfinish` (submits batch results and closes run).
  - Auth: Reads `HULY_URL`, `HULY_WORKSPACE`, `HULY_TOKEN` from environment or `pytest.ini` / `huly.toml`.
