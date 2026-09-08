# Huly Architecture Guide & Implementation Roadmap
## Comprehensive Architectural Synthesis: Multi-Screen Sharing, Video Resolution Increase, Document Markdown Export, and External Test Management Ingestion

**Document Status**: Final Architectural Synthesis & Implementation Blueprint  
**Author**: Synthesis Lead (`synthesis_lead`), Technical Lead / Synthesis  
**Team**: `huly-feature-research`  
**Reference Source Reports**:
1. `docs/HULY_ARCHITECTURE_CORE.md` — Platform Architecture, Transaction Flow, Plugin Model & API
2. `docs/HULY_MEETING_MULTI_SCREEN_SHARING.md` — Meeting Multi-Screen Sharing Analysis & UI/LiveKit Specification
3. `docs/HULY_MEETING_VIDEO_RESOLUTION_INCREASE.md` — Video & Screen Share Quality Presets, SFU & Bandwidth Engine
4. `docs/HULY_EXPORT_MARKDOWN_RESEARCH.md` — Document Modeling, Y.js/ProseMirror Serialization & Asset Export
5. `docs/HULY_TEST_MANAGEMENT_INTEGRATION.md` — Test Management Domain, Transactor Ingestion API & `pytest-huly`

---

# Table of Contents
1. [Executive Summary & Foundational Platform Architecture](#1-executive-summary--foundational-platform-architecture)
   - 1.1 Scope & Research Objectives
   - 1.2 Microservices Topology & Distributed System Map
   - 1.3 Database Architecture & Domain Storage Model
   - 1.4 Transactor 26-Step Pipeline & Object Mutation Flow
   - 1.5 Frontend Plugin System & Svelte Component Model
   - 1.6 Authentication, API Tokens & REST RPC Protocol
2. [Feature 1: Meeting Multi-Screen Sharing](#2-feature-1-meeting-multi-screen-sharing)
   - 2.1 Problem Framing & Current Limitations
   - 2.2 Root Cause Analysis: The 5 Codebase Bottlenecks
   - 2.3 Target Multi-Track Architectural Model
   - 2.4 LiveKit Client Refactoring & Track Lifecycle Management
   - 2.5 Responsive Presentation Layouts & UI Components
   - 2.6 Electron Desktop Screen Capture Multi-Source Support
3. [Feature 2: Increased Meeting Video & Screen Share Resolution](#3-feature-2-increased-meeting-video--screen-share-resolution)
   - 3.1 Current Baseline & Quality Deficits
   - 3.2 The Three-Tier Dynamic Adaptation Engine
   - 3.3 Codec Optimization Strategy: VP9 SVC, AV1 & H.264
   - 3.4 Capture Presets & Bitrate Configuration Matrix
   - 3.5 LiveKit SFU Server Limits & Network Tuning
   - 3.6 User Experience & Quality Control UI
4. [Feature 3: Exporting Documents to Markdown](#4-feature-3-exporting-documents-to-markdown)
   - 4.1 Document Domain Model & Storage Topology
   - 4.2 Collaborative State Pipeline (Y.js, Collaborator & MinIO)
   - 4.3 Rich Text AST Serialization & GFM Formatting Extensions
   - 4.4 Asset Resolution & Bundled Image Export
   - 4.5 Implementation Architectures: Client-Side vs Server-Side Headless
   - 4.6 Single Document & Full Hierarchy ZIP Packaging
5. [Feature 4: Test Management External Ingestion API & `pytest-huly`](#5-feature-4-test-management-external-ingestion-api--pytest-huly)
   - 5.1 Test Management Domain Specification & Hierarchy
   - 5.2 Transactor Mutation Payloads for Automated Ingestion
   - 5.3 Batch Transaction Processing & ID Generation
   - 5.4 Standalone Ingestion Microservice (`huly-test-ingest`)
   - 5.5 Native Pytest Plugin (`pytest-huly`) Architecture
   - 5.6 End-to-End CI/CD Automation Workflow
6. [Prioritized Implementation Roadmap & Risk Management](#6-prioritized-implementation-roadmap--risk-management)
   - 6.1 Phase 1: High-Impact Independent Wins (Weeks 1–3)
   - 6.2 Phase 2: Media Resolution & Bandwidth Engine (Weeks 4–5)
   - 6.3 Phase 3: Meeting Multi-Screen Sharing Overhaul (Weeks 6–8)
   - 6.4 Phase 4: Production Hardening, Load Testing & E2E Validation (Weeks 9–10)
   - 6.5 Architectural Risk Matrix & Mitigation Protocols
   - 6.6 Manual Verification & Acceptance Checklist

---

# 1. Executive Summary & Foundational Platform Architecture

## 1.1 Scope & Research Objectives

Huly is an all-in-one open-source collaborative workspace platform that unifies issue tracking, team chat, collaborative documentation, virtual office meetings, and test management into a single cohesive ecosystem. To support modern engineering organizations operating at enterprise scale, four critical capabilities were investigated:

1. **Meeting Multi-Screen Sharing**: Enabling simultaneous screen sharing by multiple meeting participants, as well as multi-monitor/window sharing by a single participant, with intelligent dynamic layout rendering (Side-by-Side, 2x2 Grid, and Stage + Presenter Carousel).
2. **Meeting Video & Screen Share Resolution Increase**: Elevating video communication fidelity from 720p/15fps up to Full HD (1080p), Quad HD (1440p), and 4K (2160p) at 30/60fps, governed by a Three-Tier Dynamic Adaptation Engine (Simulcast, SFU Dynacast, and AdaptiveStream) to balance visual sharpness against CPU and bandwidth constraints.
3. **Document Export to Markdown**: Providing high-fidelity client-side and server-side export of rich-text collaborative documents (ProseMirror AST / Y.js CRDT) to GitHub Flavored Markdown (GFM), including image resolution, asset archiving, frontmatter metadata, and recursive hierarchical ZIP export.
4. **External Test Management Ingestion & `pytest-huly` Package**: Developing an automated, high-throughput ingestion bridge between external CI/CD pipelines and Huly's native Test Management subsystem, featuring a standalone report ingestion service (`huly-test-ingest`) and an official Python package (`pytest-huly`).

---

## 1.2 Microservices Topology & Distributed System Map

Huly is architected around a distributed microservices topology optimized for extreme real-time reactivity, multi-tenant workspace isolation, and high horizontal scalability:

```
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│                                   CLIENT TIERS                                            │
│   Web Browser (Svelte SPA)  │  Desktop (Electron App)  │  External CI/CD & Python Scripts │
└───────────────────────┬───────────────────┬───────────────────────────┬───────────────────┘
                        │ (HTTP :8087)      │                           │ (HTTP REST RPC)
                        ▼                   │                           ▼
               ┌─────────────────┐          │                 ┌───────────────────┐
               │  Front Server   │          │                 │ External Ingest   │
               │  (:8087 nginx)  │          │                 │ (huly-test-ingest)│
               └────────┬────────┘          │                 └─────────┬─────────┘
                        │                   │ (WebSocket :3332)         │
         ┌──────────────┴───────────────────┴─────────────┐             │
         ▼                                                ▼             ▼
┌─────────────────────────┐                     ┌─────────────────────────────────┐
│     Account Service     │                     │           Transactor            │
│         (:3000)         │                     │             (:3332)             │
│ - Identity & Auth       │                     │ - 26-Step Pipeline              │
│ - Workspace Discovery   │                     │ - State Machine & Mutex         │
│ - JWT / API Tokens      │                     │ - WebSocket & REST RPC          │
└───────────┬─────────────┘                     └───────────────┬─────────────────┘
            │                                                   │
            │                  ┌────────────────────────────────┤
            ▼                  ▼                                ▼
┌───────────────────────────────────────┐             ┌───────────────────────────┐
│              CockroachDB              │             │    Redpanda / Kafka       │
│                (:26257)               │             │      (Bus :9092)          │
│ - Distributed SQL & JSONB             │             │ - Topic: workspace-tx     │
│ - Partitioned by (workspaceId, _id)   │             │ - Consumers: Search, Mail │
└───────────────────────────────────────┘             └─────────────┬─────────────┘
            ▲                  ▲                                    │
            │                  │                                    ▼
┌───────────┴──────────┐ ┌─────┴──────────────────┐   ┌───────────────────────────┐
│     Collaborator     │ │      Love Service      │   │      Fulltext Search      │
│       (:3078)        │ │        (:4030)         │   │          (:4702)          │
│ - Hocuspocus / Y.js  │ │ - LiveKit Token Broker │   │ - ElasticSearch (:9200)   │
│ - Real-time Doc Sync │ │ - Meeting Egress/Rec   │   └───────────────────────────┘
└───────────┬──────────┘ └─────────────┬──────────┘
            │                          │
            ▼                          ▼
┌───────────────────────┐ ┌───────────────────────┐
│  MinIO / S3 Storage   │ │     LiveKit SFU       │
│        (:9000)        │ │       (:7880)         │
│ - Buckets: blobs, eu  │ │ - WebRTC SFU Media    │
│ - CRDT States, Images │ │ - Audio / Video / SFU │
└───────────────────────┘ └───────────────────────┘
```

### Core Microservices Breakdown:
1. **Transactor (`pods/server`, port 3332)**: The single authoritative state machine for all data mutations and transactional queries. Manages client WebSocket sessions, validates permissions, processes mutation transactions through a 26-step pipeline, writes state to CockroachDB, emits transaction logs to Redpanda, and broadcasts changes back to subscribed clients. Also exposes an HTTP REST RPC API (`/api/v1/*`).
2. **Account Service (`server/account`, port 3000)**: Handles identity, social authentication, workspace management, and issuance/revocation of JWT session tokens and revokable API tokens.
3. **Collaborator (`server/collaborator`, port 3078)**: Built upon `@hocuspocus/server`. Serves as the authoritative Y.js CRDT synchronization server for collaborative documents, descriptions, and meeting notes. Manages in-memory document state and debounces snapshots to CockroachDB and MinIO.
4. **Love Service (`services/love`, port 4030)**: Coordinates Huly's virtual office and meeting subsystem. Interfaces with LiveKit SFU, issues room tokens, manages active participant state, and triggers headless egress recording workers.
5. **LiveKit SFU (external / container, ports 7880, 7881, 50000-60000/udp)**: WebRTC Selective Forwarding Unit providing ultra-low-latency real-time transport for audio, video, and screen sharing streams.
6. **MinIO / Hulylake (ports 9000, 8096)**: S3-compatible binary blob storage storing attachments, avatars, exported archives, and binary Y.js CRDT states.
7. **CockroachDB (ports 26257, 8089)**: Primary relational database providing distributed ACID transactions and JSONB document storage.

---

## 1.3 Database Architecture & Domain Storage Model

Huly's persistence layer (`@hcengineering/postgres`) replaces traditional single-table-per-class relational designs with **Partitioned Domain Storage**:

```sql
CREATE TABLE IF NOT EXISTS ${domain} (
  "workspaceId" uuid NOT NULL,
  _id varchar(24) NOT NULL,
  _class varchar(255) NOT NULL,
  space varchar(24),
  "modifiedOn" int8 NOT NULL,
  "modifiedBy" varchar(24) NOT NULL,
  data JSONB NOT NULL,
  PRIMARY KEY ("workspaceId", _id)
);
CREATE INDEX IF NOT EXISTS ${domain}_class_idx ON ${domain} ("workspaceId", _class);
CREATE INDEX IF NOT EXISTS ${domain}_space_idx ON ${domain} ("workspaceId", space);
```

### Storage Domains:
- `tx`: Immutable append-only log of every committed transaction (`TxCreateDoc`, `TxUpdateDoc`, etc.).
- `default`: Core workspace entities (issues, tasks, projects, test runs, test suites, test cases).
- `space`: Teamspaces, project containers, security ACLs, and folder hierarchies.
- `collaborator`: Document synchronization state and Y.js snapshot pointers.
- `document`: Collaborative document metadata, parent-child links, and content blob references.

**Multi-Tenancy Isolation**: Multi-tenancy is enforced at the database physical layer via the compound primary key `("workspaceId", _id)`. Cross-workspace data leakage is cryptographically and relationally impossible.

---

## 1.4 Transactor 26-Step Pipeline & Object Mutation Flow

Clients never execute direct SQL statements. Every mutation is submitted as a typed **Transaction (`TxCUD`)** processed sequentially by the Transactor's middleware pipeline (`server/server-pipeline/src/pipeline.ts`):

```
Client WebSocket / REST RPC (POST /api/v1/tx/:workspaceId)
  │
  ▼
[ 1. LookupMiddleware ]           ── Resolve foreign keys & relation targets
[ 2. NormalizeTxMiddleware ]       ── Standardize payload keys & data shapes
[ 3. IdentityMiddleware ]          ── Validate JWT / API Token & Session Identity
[ 4. ModifiedMiddleware ]          ── Stamp modifiedBy, modifiedOn, createdBy, createdOn
[ 5. RankMiddleware ]              ── Calculate fractional LexoRank index for ordering
[ 6. FindSecurityMiddleware ]      ── Evaluate read authorization
[ 7. PluginConfigMiddleware ]      ── Check plugin activation rules
[ 8. PrivateMiddleware ]           ── Filter private documents
[ 9. SpaceSecurityMiddleware ]     ── Enforce space-level RBAC (Admin, Member, Guest)
[10. ContextNameMiddleware ]       ── Inject execution contextual metadata
[11. CommunicationMiddleware ]     ── Route notifications to chat/threads
[12. UserStatusMiddleware ]        ── Update actor online/presence state
[13. ApplyTxMiddleware ]           ── Evaluate atomic preconditions (TxApplyIf)
[14. VersioningMiddleware ]        ── Manage auto-incrementing IDs (e.g. HULY-101)
[15. RatingMiddleware ]            ── Enforce content rating constraints
[16. TxMiddleware ]                ── Prepare transaction record for 'tx' domain
[17. TriggersMiddleware ]          ── Fire server triggers (derive atomic follow-up txs)
[18. FullTextMiddleware ]          ── Prepare text index documents for Elasticsearch
[19. LowLevelMiddleware ]          ── Linear transaction serialization lock
[20. LiveQueryMiddleware ]         ── Evaluate cache invalidation for client subscriptions
[21. DomainTxMiddleware ]          ── Route transaction to target domain table
[22. QueueMiddleware ]             ── Publish committed event to Redpanda (Kafka)
[23. DBAdapterInitMiddleware ]     ── Verify DB connection readiness
[24. ModelMiddleware ]             ── Schema validation against compiled ModelDb
[25. DBAdapterMiddleware ]         ── Commit SQL transaction into CockroachDB
[26. BroadcastMiddleware ]         ── Push committed batch to all connected WebSocket clients
```

### Transaction Primitives:
- **`TxCreateDoc`**: Creates a top-level document (`_id`, `_class`, `space`, `attributes`).
- **`TxUpdateDoc`**: Modifies an existing document via atomic operators (`$set`, `$unset`, `$push`, `$inc`).
- **`TxCollectionCUD`**: Wraps a transaction targeting an `AttachedDoc` embedded inside a collection of a parent entity (`attachedTo`, `attachedToClass`, `collection`).
- **`TxApplyIf`**: Wraps an array of transactions guarded by atomic assertions (`match`, `notMatch`).

---

## 1.5 Frontend Plugin System & Svelte Component Model

Huly's frontend is completely modular, built on Svelte and governed by `@hcengineering/platform`. Each plugin is decomposed into four discrete packages:

| Monorepo Path | Role | Description |
|---|---|---|
| `plugins/<name>` | Contract | Declares plugin ID, class references, PRI constants, icons, strings, and extension points. Pure types, zero bundle bloat. |
| `plugins/<name>-assets` | Static Assets | SVG icons, branding artwork, and static media files. |
| `plugins/<name>-resources` | Implementation | Svelte components, action handlers, layout views, and completion providers. Dynamically loaded on demand. |
| `server-plugins/<name>` | Server Logic | Server-side triggers, HTML/markdown formatters, and Transactor validation hooks. |

**Reactivity via `LiveQuery`**: Svelte components obtain the active client via `getClient()` and create reactive queries with `createQuery()`. When transactions are committed by the Transactor, the WebSocket broadcast pushes mutations to the client, invalidating the query cache and triggering fine-grained Svelte re-renders with zero full-page reloads.

---

## 1.6 Authentication, API Tokens & REST RPC Protocol

Service-to-service communication, web sessions, and external integrations use signed JWTs generated via `@hcengineering/server-token`:

```typescript
interface Token {
  account: AccountUuid      // User UUID in account service
  workspace: WorkspaceUuid  // Workspace UUID
  extra?: {
    apiTokenId?: string     // Present if this is a revokable Personal Access Token
    service?: string        // Present if issued by an internal service (e.g. 'transactor')
    admin?: 'true'          // Administrative superuser flag
  }
  exp?: number              // Expiration timestamp (seconds)
}
```

### Transactor REST RPC Endpoints (`pods/server/src/rpc.ts`):
External automated systems interact with Huly over HTTP without maintaining persistent WebSocket state:

- `GET /api/v1/ping/:workspaceId`: Health check and latest committed transaction sequence.
- `GET /api/v1/generate-id/:workspaceId`: Returns a valid 24-character hex ID (`^[0-9a-f]{24}$`).
- `POST /api/v1/find-all/:workspaceId`: Queries entities by class and criteria (`{ "_class": "...", "query": { ... } }`).
- `POST /api/v1/tx/:workspaceId`: Executes an atomic transaction (`TxCreateDoc`, `TxUpdateDoc`, `TxCollectionCUD`, or `TxApplyIf`).
- Header: `Authorization: Bearer <apiToken>` with `Content-Type: application/json`.

---

# 2. Feature 1: Meeting Multi-Screen Sharing

## 2.1 Problem Framing & Current Limitations

Huly's virtual meeting module ("Love") uses LiveKit SFU for WebRTC communication. Although LiveKit natively supports publishing an arbitrary number of simultaneous video tracks (from multiple participants or multiple displays on a single machine), Huly currently limits meetings to **exactly one active screen share across the entire room**.

If User A is sharing their screen, no other participant can share, and User A cannot share a second display.

---

## 2.2 Root Cause Analysis: The 5 Codebase Bottlenecks

A comprehensive audit of `plugins/love-resources` identified five concrete bottlenecks enforcing this limitation:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        ROOT CAUSE IDENTIFICATION: 5 BOTTLENECKS                        │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 1. Tri-State Enum Store (plugins/love-resources/src/liveKitClient.ts)                  │
│    - export enum ScreenSharingState { Inactive, Local, Remote }                        │
│    - When Remote track arrives, overwrites state to Remote, destroying Local state.    │
│    - When ANY remote track stops, resets state to Inactive, dropping other shares.     │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 2. Hard-Coded UI Disabling (ShareScreenButton.svelte & SharingStateIndicator.svelte)   │
│    - disabled={$screenSharingState === ScreenSharingState.Remote || !$lkConnected}     │
│    - Button is disabled for all users whenever anyone in the room is sharing.          │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 3. Single <video> Element & Loop Break (ScreenSharingView.svelte)                      │
│    - Template contains exactly ONE <video bind:this={screen}> tag.                     │
│    - onMount loop breaks on first track: if (trySetActiveTrack(pub.track)) break;      │
│    - Ignores all subsequent tracks published by other participants.                    │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 4. Binary Room Container Layout (Room.svelte)                                          │
│    - class:sharing={withScreenSharing} where withScreenSharing is a single boolean.    │
│    - sharing=true forces a 15rem right sidebar for webcams and 1 giant center stage.   │
│    - No layout structure for rendering 2 or more screen shares side-by-side or in grid.│
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 5. Single Track API Wrapper in LiveKit Client & Electron Dialog                        │
│    - localParticipant.setScreenShareEnabled() only manages a single track instance.    │
│    - desktop/src/ui/screenShare.ts allows selecting only one source window/monitor.    │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2.3 Target Multi-Track Architectural Model

### Data Structures (`plugins/love-resources/src/types.ts`):
```typescript
import { Track, TrackPublication, Participant } from 'livekit-client'

export interface ActiveScreenShare {
  id: string                    // publication.trackSid
  track: Track
  publication: TrackPublication
  participant: Participant
  isLocal: boolean
  sourceName?: string           // e.g., "Screen 1 - 4K", "Visual Studio Code"
  displaySurface?: 'monitor' | 'window' | 'browser'
}

export type ScreenShareLayoutMode = 'auto' | 'grid' | 'focused' | 'side-by-side'
```

### Reactive Svelte Stores (`plugins/love-resources/src/stores.ts`):
```typescript
import { writable, derived, type Readable } from 'svelte/store'
import type { ActiveScreenShare, ScreenShareLayoutMode } from './types'

// Primary collection of active screen shares
export const activeScreenShares = writable<Map<string, ActiveScreenShare>>(new Map())

// Manually focused screen share (null = automatic grid/side-by-side)
export const focusedScreenShareId = writable<string | null>(null)

// Preferred layout mode
export const screenShareLayoutMode = writable<ScreenShareLayoutMode>('auto')

// Derived reactive helpers
export const screenSharesList: Readable<ActiveScreenShare[]> = derived(
  activeScreenShares,
  ($shares) => Array.from($shares.values())
)

export const hasActiveScreenShares: Readable<boolean> = derived(
  activeScreenShares,
  ($shares) => $shares.size > 0
)

export const localScreenShares: Readable<ActiveScreenShare[]> = derived(
  activeScreenShares,
  ($shares) => Array.from($shares.values()).filter((s) => s.isLocal)
)

export const isLocalScreenSharing: Readable<boolean> = derived(
  localScreenShares,
  ($local) => $local.length > 0
)

export const remoteScreenShares: Readable<ActiveScreenShare[]> = derived(
  activeScreenShares,
  ($shares) => Array.from($shares.values()).filter((s) => !s.isLocal)
)
```

---

## 2.4 LiveKit Client Refactoring & Track Lifecycle Management

In `plugins/love-resources/src/liveKitClient.ts`:

1. **Registration Methods**:
```typescript
private registerScreenTrack(
  track: Track,
  publication: TrackPublication,
  participant: Participant,
  isLocal: boolean
): void {
  if (track.kind !== Track.Kind.Video || publication.source !== Track.Source.ScreenShare) return
  const id = publication.trackSid || track.sid || `${participant.identity}-${Date.now()}`
  const settings = track.mediaStreamTrack?.getSettings()

  activeScreenShares.update((map) => {
    map.set(id, {
      id,
      track,
      publication,
      participant,
      isLocal,
      sourceName: publication.trackName || track.name,
      displaySurface: (settings as any)?.displaySurface
    })
    return new Map(map)
  })
}

private unregisterScreenTrack(publication: TrackPublication): void {
  const id = publication.trackSid
  activeScreenShares.update((map) => {
    map.delete(id)
    return new Map(map)
  })
  focusedScreenShareId.update((current) => (current === id ? null : current))
}
```

2. **Event Listeners**:
- `onTrackSubscribed`: calls `registerScreenTrack(track, publication, participant, false)`.
- `onTrackUnsubscribed`: calls `unregisterScreenTrack(publication)`.
- `onLocalTrackPublished`: calls `registerScreenTrack(publication.track, publication, participant, true)`.
- `onLocalTrackUnpublished`: calls `unregisterScreenTrack(publication)`.

3. **Multi-Track Publishing API**:
```typescript
async publishAdditionalScreenShare(customTracks?: Array<LocalTrack>): Promise<LocalTrackPublication | undefined> {
  let tracks = customTracks
  if (!tracks) {
    tracks = await createScreenTracks({
      audio: false,
      resolution: ScreenSharePresets.h1080fps30.resolution
    })
  }
  const videoTrack = tracks.find((t) => t.kind === Track.Kind.Video)
  if (videoTrack) {
    return await this.liveKitRoom.localParticipant.publishTrack(videoTrack, {
      source: Track.Source.ScreenShare,
      name: `screen-${Date.now()}`
    })
  }
}

async stopScreenShare(trackSid: string): Promise<void> {
  const pub = this.liveKitRoom.localParticipant.getTrackPublication(trackSid)
  if (pub?.track) {
    await this.liveKitRoom.localParticipant.unpublishTrack(pub.track, true)
  }
}
```

---

## 2.5 Responsive Presentation Layouts & UI Components

### Layout Modes:
```
1. Side-by-Side (2 Screens)           2. 2x2 Grid (3-4 Screens)          3. Stage + Presenter Carousel
┌──────────────────┬──────────────────┐  ┌───────────────┬───────────────┐  ┌─────────────────────────┬─────────┐
│                  │                  │  │ Screen 1      │ Screen 2      │  │                         │ Screen 2│
│ Screen 1         │ Screen 2         │  │ (Presenter A) │ (Presenter B) │  │ Focused Stage           ├─────────┤
│ (Presenter A)    │ (Presenter B)    │  ├───────────────┼───────────────┤  │ Screen 1                │ Screen 3│
│                  │                  │  │ Screen 3      │ Screen 4      │  │ (Presenter A)           ├─────────┤
│                  │                  │  │ (Presenter C) │ (Presenter D) │  │                         │ Screen 4│
└──────────────────┴──────────────────┘  └───────────────┴───────────────┘  └─────────────────────────┴─────────┘
```

### Component Breakdown:
1. **`ScreenTile.svelte` (New Subcomponent)**:
   - Encapsulates one `<video>` element with `track.attach(videoEl)` on mount and `track.detach()` on destroy.
   - Overlays participant avatar, display name, and screen name tag.
   - Action controls: Focus/Pin button, Fullscreen toggle, and Stop Sharing button (if `isLocal`).
2. **`ScreenSharingView.svelte` (Refactored)**:
   - Iterates over `$screenSharesList` using Svelte `{#each $screenSharesList as share (share.id)}`.
   - Computes CSS grid layout dynamically based on `$screenSharesList.length` and `$screenShareLayoutMode`.
3. **`ShareScreenButton.svelte` (Refactored)**:
   - Removes `disabled={$screenSharingState === ScreenSharingState.Remote}`.
   - When already sharing, the split button dropdown offers: "Share Another Screen / Window" or "Stop All Shares".

---

## 2.6 Electron Desktop Screen Capture Multi-Source Support

In `desktop/src/ui/screenShare.ts`:
- Modify `SelectScreenSourcePopup.svelte` to support multi-selection mode (checkboxes on monitor/window thumbnails).
- Return an array of selected source IDs `string[]`.
- Loop over selected IDs and publish separate `LocalTrack` instances via `liveKitClient.publishAdditionalScreenShare()`.

---

# 3. Feature 2: Increased Meeting Video & Screen Share Resolution

## 3.1 Current Baseline & Quality Deficits

1. **Camera Hardcoded to 720p**: `liveKitClient.ts` captures video with `{ width: 1280, height: 720, frameRate: 30 }`. High-end webcams (1080p, 4K) are artificially downscaled.
2. **Missing Video Encoding Settings**: LiveKit room defaults omit `videoEncoding`, falling back to LiveKit SDK default ~1.5 Mbps.
3. **Screen Share Capped at 15fps**: `screenShareEncoding.maxFramerate` is locked at `15`, causing choppy scrolling and stuttering animations.
4. **Server Egress Defaults to 720p**: `services/love/src/preset.ts` defaults meeting recording egress to `EncodingOptionsPreset.H264_720P_30`.

---

## 3.2 The Three-Tier Dynamic Adaptation Engine

Directly sending 1080p or 4K to all participants would overload upload bandwidth and throttle mobile devices. Huly resolves this using a **Three-Tier Dynamic Adaptation Engine**:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        THREE-TIER DYNAMIC ADAPTATION ENGINE                            │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ TIER 1: CLIENT SIMULCAST (Publisher)                                                   │
│ Encode 3 simultaneous spatial layers:                                                  │
│ - High:   1080p @ 3.2 Mbps (or 4K @ 8.0 Mbps for screen share)                         │
│ - Medium: 540p  @ 800 kbps (or 1080p @ 2.5 Mbps)                                       │
│ - Low:    270p  @ 180 kbps (or 540p  @ 500 kbps)                                       │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ TIER 2: SFU DYNACAST (LiveKit Server)                                                  │
│ LiveKit SFU monitors all subscriber display requirements:                              │
│ - If NO subscriber requests the High layer, SFU instructs the publisher to PAUSE the   │
│   High layer. Saves up to 70% upload bandwidth and encoding CPU!                      │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ TIER 3: ADAPTIVE STREAM (Subscriber Client)                                            │
│ Subscriber measures DOM element dimensions:                                            │
│ - Participant in 15rem sidebar (~240px wide) -> subscribes to Low layer (270p).        │
│ - Participant in 2x2 grid (~600px wide)      -> subscribes to Medium layer (540p).     │
│ - Focused / Fullscreen stage (>1200px wide)  -> subscribes to High layer (1080p/4K).   │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

Both `dynacast: true` and `adaptiveStream: true` are already instantiated in `LiveKitClient`'s constructor. They become fully operational once simulcast layers and resolution profiles are configured.

---

## 3.3 Codec Optimization Strategy: VP9 SVC, AV1 & H.264

| Codec | Usage Profile | Architectural Justification |
|---|---|---|
| **VP9 (SVC)** | Webcam Video (720p / 1080p / 1440p) | Scalable Video Coding (`L3T3_KEY`) provides temporal/spatial scalability inside a single bitstream. Saves 30% bitrate compared to H.264 without encoding 3 separate simulcast streams. |
| **AV1** | Screen Sharing (1080p / 1440p / 4K) | Unrivaled compression efficiency for sharp fonts, code editors, and vector graphics. Eliminates macroblocking on high-DPI displays. |
| **H.264** | Universal Fallback | Universal hardware decode acceleration for legacy laptops and mobile devices, preventing thermal throttling. |

---

## 3.4 Capture Presets & Bitrate Configuration Matrix

### Quality Profiles (`plugins/love-resources/src/presets.ts`):

```typescript
export const CAMERA_PROFILES = {
  low: {
    capture: { resolution: { width: 640, height: 360, frameRate: 24 } },
    encoding: { maxBitrate: 450_000, maxFramerate: 24 },
    simulcast: false
  },
  medium: { // 720p
    capture: { resolution: { width: 1280, height: 720, frameRate: 30 } },
    encoding: { maxBitrate: 1_700_000, maxFramerate: 30 },
    simulcast: true
  },
  high: { // 1080p Full HD (New Default)
    capture: { resolution: { width: 1920, height: 1080, frameRate: 30 } },
    encoding: { maxBitrate: 3_200_000, maxFramerate: 30 },
    simulcast: true
  },
  ultra: { // 1440p / 4K (High-end setups)
    capture: { resolution: { width: 2560, height: 1440, frameRate: 30 } },
    encoding: { maxBitrate: 6_000_000, maxFramerate: 30 },
    simulcast: true
  }
}

export const SCREEN_SHARE_PROFILES = {
  '1080p15': { // Text/Static slides
    resolution: { width: 1920, height: 1080, frameRate: 15 },
    encoding: { maxBitrate: 1_500_000, maxFramerate: 15 }
  },
  '1080p30': { // Standard dynamic sharing
    resolution: { width: 1920, height: 1080, frameRate: 30 },
    encoding: { maxBitrate: 3_000_000, maxFramerate: 30 }
  },
  '1440p30': { // 2K Displays / Ultra-wide
    resolution: { width: 2560, height: 1440, frameRate: 30 },
    encoding: { maxBitrate: 5_000_000, maxFramerate: 30 }
  },
  '4k15': { // 4K High Detail (Architecture diagrams, CAD, IDE)
    resolution: { width: 3840, height: 2160, frameRate: 15 },
    encoding: { maxBitrate: 5_000_000, maxFramerate: 15 }
  },
  '4k30': { // 4K Fluid (Design animation, video demo)
    resolution: { width: 3840, height: 2160, frameRate: 30 },
    encoding: { maxBitrate: 8_500_000, maxFramerate: 30 }
  }
}
```

---

## 3.5 LiveKit SFU Server Limits & Network Tuning

To support 1080p and 4K streams without server-side packet dropping, update `livekit.yaml`:

```yaml
limit:
  max_publisher_bitrate: 15000000 # 15 Mbps (permits 4K @ 8.5 Mbps + 1080p camera @ 3.2 Mbps)
rtc:
  tcp_fallback: true
  congestion_control:
    congestion_controller: bbr # Google BBR congestion control
    loss_based_bandwidth_estimation: false
```

### Server Egress Recording Presets (`services/love/src/preset.ts`):
Extend recording presets to support 1080p and 4K output archives:
- `RecordingPreset1080p`: `1920x1080 @ 30fps`, `EncodingOptionsPreset.H264_1080P_30` (4.5 Mbps).
- `RecordingPreset4K`: `3840x2160 @ 30fps`, `EncodingOptionsPreset.H264_4K_30` (12.0 Mbps).

---

## 3.6 User Experience & Quality Control UI

1. **`CamSettingPopup.svelte`**:
   - Add quality selector: `Low (360p)`, `Standard (720p)`, `Full HD (1080p) [Default]`, `Ultra HD (1440p)`.
   - Persists selection to `DevicesPreference.cameraQuality`.
2. **`ShareSettingPopup.svelte`**:
   - Quality preset: `1080p 30fps`, `1440p 30fps`, `4K 15fps (High Detail)`, `4K 30fps (Fluid)`.
   - Mode toggle: `Optimize for Text & Code` vs `Optimize for Motion & Video`.
   - Persists selection to `DevicesPreference.screenShareQuality`.

---

# 4. Feature 3: Exporting Documents to Markdown

## 4.1 Document Domain Model & Storage Topology

Documents in Huly are defined in `models/document/src/index.ts`:

```typescript
@Model(document.class.Document, core.class.Doc, 'document')
export class TDocument extends TDoc implements Document {
  title!: string
  content!: MarkupBlobRef | null // Collaborative blob reference
  parent!: Ref<Document>         // Parent document in hierarchy (or core:doc:nil)
  space!: Ref<Teamspace>
  rank!: Rank                    // LexoRank tree ordering
}
```

### Physical Storage Architecture:
1. **CockroachDB (`document` table)**: Stores document metadata, space partition, parent pointer, and blob reference (`content: "673abc...-content-170..."`).
2. **MinIO Object Storage (`blobs` bucket)**:
   - Binary Y.js CRDT state: Key `${objectId}%content`, content-type `application/ydoc`.
   - Frozen ProseMirror JSON string: Key `${objectId}-content-${timestamp}`, content-type `application/json`.

---

## 4.2 Collaborative State Pipeline (Y.js, Collaborator & MinIO)

```
[ Active Document Editor (TipTap / Svelte) ]
                    │
                    ▼ (WebSocket Y.js delta protocol)
[ Collaborator Service (server/collaborator / @hocuspocus/server) ]
  - In-Memory Y.Doc CRDT
  - 10-Second Debounce Flush:
      ├── 1. saveCollabYdoc() -> MinIO "${objectId}%content" (binary Y.Doc)
      ├── 2. yDocToMarkup()   -> JSON AST
      ├── 3. saveCollabJson() -> MinIO "${objectId}-content-${ts}" (frozen JSON)
      └── 4. Transactor Tx    -> Updates doc.content pointer in CockroachDB
```

---

## 4.3 Rich Text AST Serialization & GFM Formatting Extensions

Huly rich text uses `@hcengineering/text-core` (`MarkupNode` tree).
The existing `@hcengineering/text-markdown` package provides `markupToMarkdown()`, but requires three key enhancements for complete Markdown compliance:

### 1. GFM Pipe Table Serializer (`foundations/core/packages/text-markdown/src/serializer.ts`):
Replace raw HTML `<table>` rendering with GitHub Flavored Markdown pipe tables:

```typescript
function renderGfmTable(state: MarkdownSerializerState, node: MarkupNode): void {
  const rows = node.content?.filter((n) => n.type === 'tableRow') || []
  if (rows.length === 0) return

  const tableMatrix: string[][] = []
  for (const row of rows) {
    const cells = row.content || []
    tableMatrix.push(cells.map((cell) => {
      // Serialize inner inline nodes to markdown text
      return state.renderInline(cell).replace(/\|/g, '\\|').replace(/\n/g, ' ')
    }))
  }

  const colCount = Math.max(...tableMatrix.map((r) => r.length))
  // Header row
  const header = tableMatrix[0] || []
  state.write('| ' + Array.from({ length: colCount }, (_, i) => header[i] || '').join(' | ') + ' |\n')
  // Delimiter row
  state.write('| ' + Array.from({ length: colCount }, () => '---').join(' | ') + ' |\n')
  // Body rows
  for (let r = 1; r < tableMatrix.length; r++) {
    const row = tableMatrix[r]
    state.write('| ' + Array.from({ length: colCount }, (_, i) => row[i] || '').join(' | ') + ' |\n')
  }
  state.closeBlock(node)
}
```

### 2. Missing Node Serializers:
- `file` / `attachment`: Format as `[📎 filename (size)](url)`.
- `drawingBoard`: Format as `![Drawing: title](previewUrl)`.
- `taskList` / `taskItem`: Format as GFM task checkboxes `- [x] Completed task` / `- [ ] Incomplete task`.
- `codeBlock`: Preserve language syntax tag (` ```typescript ... ``` `).

---

## 4.4 Asset Resolution & Bundled Image Export

Huly stores embedded images as platform URIs:
`platform://platform/files/download?fileId=<blobId>` or `image://<blobId>`.

### Resolution Strategies:
1. **Single `.md` File Export**:
   - Rewrite internal URIs to absolute authenticated URLs:
     `https://<huly-host>/blob/<workspaceUuid>/<blobId>/<filename>`.
2. **Zipped Archive Export (`.zip`)**:
   - Use `JSZip` to bundle `${docTitle}.md` alongside an `assets/` subfolder.
   - Fetch image binary data via `fetch(blobUrl, { headers: { Authorization: bearerToken } })`.
   - Write image to `zip.file("assets/image-1.png", blobData)`.
   - Rewrite markdown image links to relative paths: `![Alt Text](./assets/image-1.png)`.

---

## 4.5 Implementation Architectures: Client-Side vs Server-Side Headless

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        MARKDOWN EXPORT: TWO PARALLEL PATHS                             │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ PATH A: CLIENT-SIDE EXPORT (Interactive User Action)                                   │
│ - Located in plugins/document-resources. Triggered from Document "..." action menu.    │
│ - Zero server CPU overhead.                                                            │
│ - Extracts uncommitted edits directly from live TipTap editor via editor.getJSON().    │
│ - Generates download in browser via Blob() + URL.createObjectURL() + <a download>.     │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ PATH B: SERVER-SIDE HEADLESS API (Automated CLI / CI / Backup)                         │
│ - Exposes GET /api/v1/documents/:id/export/markdown.                                   │
│ - Authenticates via API Token (Authorization: Bearer <token>).                         │
│ - Collaborator RPC fetches Y.Doc or frozen JSON blob from MinIO.                      │
│ - Returns Content-Type: text/markdown; charset=utf-8 with Content-Disposition header.   │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 4.6 Single Document & Full Hierarchy ZIP Packaging

### Optional Frontmatter Header:
```markdown
---
title: "Platform Engineering Strategy"
documentId: "673abc111111111111111111"
space: "Core Engineering"
author: "Ruben Harutyunyan"
createdAt: "2024-05-15T10:30:00Z"
updatedAt: "2024-05-18T14:20:00Z"
tags: [architecture, backend, webrtc]
---

# Platform Engineering Strategy
...
```

### Recursive Hierarchy Export:
When exporting a parent document or entire space:
- Walk parent-child links: `docs.filter(d => d.parent === currentDoc._id)`.
- Recreate nested folder structure in `JSZip`:
  ```
  Engineering Space/
  ├── Architecture Overview.md
  ├── assets/
  │   └── diagram1.png
  └── Services/
      ├── Transactor.md
      └── Collaborator.md
  ```

---

# 5. Feature 4: Test Management External Ingestion API & `pytest-huly`

## 5.1 Test Management Domain Specification & Hierarchy

Defined in `models/test-management/src/types.ts`:

```
┌─────────────────────────────────────────────────────────────────┐
│                 TestProject (TypedSpace / Doc)                  │
│               Class: testManagement:class:TestProject           │
└────────────────┬───────────────────────────────┬────────────────┘
                 │ contains                      │ contains
                 ▼                               ▼
┌─────────────────────────────────┐ ┌─────────────────────────────┐
│        TestSuite (Doc)          │ │       TestRun (Doc)         │
│  Class: ...:TestSuite           │ │  Class: ...:TestRun         │
│  parent: Ref<TestSuite>         │ │  dueDate: Timestamp         │
│  testCases: CollectionSize      │ │  results: CollectionSize    │
└────────────────┬────────────────┘ └──────────────┬──────────────┘
                 │ contains ('testCases')          │ contains ('results')
                 ▼                                 ▼
┌─────────────────────────────────┐ ┌─────────────────────────────┐
│       TestCase (AttachedDoc)    │ │   TestResult (AttachedDoc)  │
│  Class: ...:TestCase            │ │  Class: ...:TestResult      │
│  attachedTo: TestSuite._id      │ │  attachedTo: TestRun._id    │
│  type: TestCaseType             │ │  testCase: TestCase._id     │
│  priority: TestCasePriority     │ │  status: TestRunStatus      │
└─────────────────────────────────┘ └─────────────────────────────┘
```

### Numeric Enums:
- **`TestRunStatus`**: `0: Untested`, `1: Blocked / Skipped`, `2: Passed`, `3: Failed`.
- **`TestCasePriority`**: `0: Low`, `1: Medium`, `2: High`, `3: Urgent`.
- **`TestCaseType`**: `0: Functional`, `1: Performance`, `2: Regression`, `3: Security`, `4: Smoke`, `5: Usability`.

---

## 5.2 Transactor Mutation Payloads for Automated Ingestion

### Step 1: Create `TestRun` (`TxCreateDoc`):
```json
{
  "_id": "673abc000000000000000001",
  "_class": "core:class:TxCreateDoc",
  "objectId": "673abc111111111111111111",
  "objectClass": "testManagement:class:TestRun",
  "objectSpace": "673abc999999999999999999",
  "attributes": {
    "name": "Pytest CI Run #142 - commit 9f12ab",
    "dueDate": 1747584000000
  }
}
```

### Step 2: Create `TestResult` Attached to `TestRun` (`TxCreateDoc` / `TxCollectionCUD`):
```json
{
  "_id": "673abc000000000000000002",
  "_class": "core:class:TxCreateDoc",
  "objectId": "673abc222222222222222222",
  "objectClass": "testManagement:class:TestResult",
  "objectSpace": "673abc999999999999999999",
  "attachedTo": "673abc111111111111111111",
  "attachedToClass": "testManagement:class:TestRun",
  "collection": "results",
  "attributes": {
    "name": "tests/test_auth.py::test_jwt_login",
    "testCase": "673abc333333333333333333",
    "testSuite": "673abc444444444444444444",
    "status": 2,
    "description": null
  }
}
```

---

## 5.3 Batch Transaction Processing & ID Generation

### Local 24-Character Hex ID Generator (Zero Latency):
```python
import time
import secrets

def generate_huly_id() -> str:
    """Generate 24-hex ID matching Huly's generateId() specification."""
    ts = f"{int(time.time()):08x}"
    rnd = secrets.token_hex(5)
    cnt = secrets.token_hex(3)
    return f"{ts}{rnd}{cnt}"
```

### Batching via `TxApplyIf`:
To ingest large test suites (1,000+ tests) without opening 1,000 separate HTTP connections, wrap mutations in a single `TxApplyIf` transaction batch sent to `POST /api/v1/tx/:workspaceId`. A batch of 500 results commits in CockroachDB in under 150ms.

---

## 5.4 Standalone Ingestion Microservice (`huly-test-ingest`)

A lightweight FastAPI / Python service deployed alongside Huly or in CI:

```
┌─────────────────────────────────────────────────────────────┐
│                 huly-test-ingest Microservice               │
│                  (FastAPI on Docker :8095)                  │
├─────────────────────────────────────────────────────────────┤
│ 1. POST /api/v1/ingest/junit-xml                            │
│    - Ingests standard JUnit XML report                      │
│ 2. POST /api/v1/ingest/pytest-json                          │
│    - Ingests pytest-json-report payload                     │
│ 3. POST /api/v1/ingest/allure                               │
│    - Ingests Allure results bundle                          │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                    Entity Reconciler                        │
│ - Matches or auto-creates TestSuite (directory/module)      │
│ - Matches or auto-creates TestCase (test function/name)     │
│ - Generates TestRun & attaches TestResult batch             │
└──────────────────────────────┬──────────────────────────────┘
                               │ POST /api/v1/tx/:workspaceId
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 Huly Transactor (:3332)                     │
└─────────────────────────────────────────────────────────────┘
```

---

## 5.5 Native Pytest Plugin (`pytest-huly`) Architecture

### Package Structure:
```
pytest-huly/
├── pyproject.toml
├── README.md
└── pytest_huly/
    ├── __init__.py
    ├── client.py        # HTTP client for Huly Transactor REST RPC
    ├── reconciler.py    # Auto-matching suites and test cases
    ├── models.py        # Typed dataclasses (TestRun, TestResult, etc.)
    └── plugin.py        # Pytest hook implementations
```

### Pytest Hooks Implementation:
1. `pytest_addoption(parser)`: Adds `--huly`, `--huly-run-name`, `--huly-project`.
2. `pytest_configure(config)`: Reads credentials (`HULY_URL`, `HULY_WORKSPACE`, `HULY_TOKEN`) from env or `pytest.ini`.
3. `pytest_sessionstart(session)`: Authenticates with Huly and creates the `TestRun`.
4. `pytest_runtest_makereport(item, call)`: Records duration, outcome, and error tracebacks.
5. `pytest_sessionfinish(session)`: Flushes test results via `TxApplyIf` batch and marks the run completed.

### Custom Test Markers:
```python
import pytest

@pytest.mark.huly_case("673abc333333333333333333")
@pytest.mark.huly_priority("high")
@pytest.mark.huly_type("smoke")
def test_payment_processing():
    assert process_payment(amount=100) is True
```

---

## 5.6 End-to-End CI/CD Automation Workflow

```yaml
# .github/workflows/test.yml
name: Backend CI & Huly Test Sync

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-huly

      - name: Run Pytest with Huly Reporting
        env:
          HULY_URL: "https://huly.company.com"
          HULY_WORKSPACE: "${{ secrets.HULY_WORKSPACE_ID }}"
          HULY_TOKEN: "${{ secrets.HULY_API_TOKEN }}"
        run: |
          pytest --huly \
            --huly-project="Core Platform" \
            --huly-run-name="GitHub CI #${{ github.run_number }} - commit ${{ github.sha }}"
```

---

# 6. Prioritized Implementation Roadmap & Risk Management

## 6.1 Integrated 4-Phase Delivery Roadmap

```
2024 Delivery Roadmap
──────────────────────────────────────────────────────────────────────────────────
Phase 1: Quick Wins & Foundational Bridges (Weeks 1–3)
├── [Doc] GFM Table & Attachment Serializer in @hcengineering/text-markdown
├── [Doc] Client-Side Single Document & ZIP Export Action in plugins/document-resources
├── [Test] Python ID Generator & Transactor Client in pytest-huly
└── [Test] Ingestion Service (huly-test-ingest) JUnit XML parser
──────────────────────────────────────────────────────────────────────────────────
Phase 2: Meeting Video & Screen Share Resolution (Weeks 4–5)
├── [Media] Define Quality Presets in plugins/love & plugins/love-resources
├── [Media] Tune livekit.yaml max_publisher_bitrate to 15 Mbps
├── [Media] Configure VP9 SVC and AV1 codecs in LiveKitClient
├── [Media] Add Quality Controls in CamSettingPopup & ShareSettingPopup
└── [Media] Add 1080p and 4K presets in services/love egress recording
──────────────────────────────────────────────────────────────────────────────────
Phase 3: Meeting Multi-Screen Sharing Overhaul (Weeks 6–8)
├── [Media] Replace ScreenSharingState enum with activeScreenShares store Map
├── [Media] Refactor LiveKitClient to register/unregister multi-tracks
├── [Media] Build ScreenTile.svelte subcomponent
├── [Media] Implement dynamic Grid, Side-by-Side, and Stage layouts in ScreenSharingView
├── [Media] Update ShareScreenButton to allow publishing additional screen shares
└── [Media] Multi-monitor source selection in desktop/src/ui/screenShare.ts
──────────────────────────────────────────────────────────────────────────────────
Phase 4: Hardening, Load Testing & E2E Validation (Weeks 9–10)
├── [All] Load testing 4K multi-screen sharing across 10 participants
├── [All] Bulk document export testing (100+ documents with large assets)
├── [All] Ingestion load testing (5,000 test results in single CI run)
└── [All] Final documentation & user guides
──────────────────────────────────────────────────────────────────────────────────
```

---

## 6.2 Architectural Risk Matrix & Mitigation Protocols

| Risk ID | Feature Area | Risk Description | Severity | Probability | Architectural Mitigation Protocol |
|---|---|---|---|---|---|
| **R-01** | Meeting Media | Bandwidth saturation & CPU exhaustion when publishing 4K / multi-shares. | High | High | Enforce LiveKit **SFU Dynacast** and **AdaptiveStream**. Auto-pause 4K layer if no client renders full-screen. Limit camera to 720p when sharing 4K screen on laptops. |
| **R-02** | Meeting Media | Svelte component memory leak from un-detached WebRTC `<video>` elements. | High | Medium | Encapsulate `<video>` binding strictly in `ScreenTile.svelte` with guaranteed `track.detach()` inside `onDestroy()`. |
| **R-03** | Test Ingestion | Transactor transaction pipeline queue congestion during 5,000+ test ingest. | High | Medium | Enforce batching via `TxApplyIf` in chunks of 250–500 tests. Never send individual HTTP requests per test result. |
| **R-04** | Test Ingestion | Orphaned test results if `TestRun` creation fails. | Medium | Low | Execute `TestRun` creation as a prerequisite transaction before streaming result batches. Reconcile on client side. |
| **R-05** | Document Export | Out-of-memory error during large ZIP exports with hundreds of high-res images. | Medium | Medium | Stream assets using sequential asynchronous chunks. Limit client-side bulk export to spaces with <250 MB total assets; redirect larger spaces to server-side API. |
| **R-06** | Document Export | Broken image links in exported Markdown due to authentication timeouts. | Medium | Low | Generate temporary presigned S3 URLs with a 7-day expiration for external Markdown downloads, or bundle images locally in `.zip`. |

---

## 6.3 Manual Verification & Acceptance Checklist

As mandated by project safety instructions, automated build verification must be complemented by **rigorous manual verification**:

### Feature 1: Multi-Screen Sharing Checklist
- [ ] User A and User B join the same meeting room.
- [ ] User A starts screen sharing. Verify User B sees User A's screen on the main stage.
- [ ] Verify User B's "Share Screen" button remains **enabled** (not grayed out).
- [ ] User B clicks "Share Screen" and selects a window.
- [ ] Verify both screens render side-by-side in equal aspect ratio.
- [ ] User A clicks "Share Another Screen" from Electron desktop app.
- [ ] Verify layout automatically transitions to a 3-tile grid or Stage + Carousel.
- [ ] Click the "Focus / Pin" icon on Screen 2. Verify Screen 2 takes the main stage while Screens 1 and 3 move to the thumbnail bar.
- [ ] User A stops sharing Screen 1. Verify Screen 2 remains active without visual glitch or disconnection.

### Feature 2: High Resolution Video Checklist
- [ ] Connect a 1080p or 4K webcam. Open `CamSettingPopup`.
- [ ] Select "Full HD (1080p)". Verify camera stream switches to 1080p30.
- [ ] Open Chrome `chrome://webrtc-internals`. Inspect `outbound-rtp` video track:
  - Verify width = 1920, height = 1080.
  - Verify bitrate scales to 2.5–3.2 Mbps.
- [ ] Open `ShareSettingPopup`, select "4K 30fps (Fluid)".
- [ ] Share a 4K monitor. Verify receiver displays crisp code text without blurriness.
- [ ] Resize receiver window down to 300px width. Verify `inbound-rtp` switches to lower simulcast layer, reducing downstream bandwidth.

### Feature 3: Document Markdown Export Checklist
- [ ] Create a document with headings, bold/italic text, code blocks, task lists, tables, and embedded images.
- [ ] Click document "..." menu -> "Export as Markdown".
- [ ] Verify `.md` file downloads immediately.
- [ ] Open `.md` in VS Code / Obsidian:
  - Verify tables render as clean GFM pipe tables (`| col | col |`).
  - Verify task lists render as `- [ ]` and `- [x]`.
  - Verify images display properly with valid URLs.
- [ ] Click "Export as ZIP (with assets)". Verify downloaded `.zip` contains `${title}.md` and an `assets/` directory containing downloaded image files.

### Feature 4: Test Management Ingestion Checklist
- [ ] Generate an API token in Huly Web UI (`Settings` -> `API Tokens`).
- [ ] Configure `HULY_URL`, `HULY_WORKSPACE`, and `HULY_TOKEN` in a Python test repository.
- [ ] Run `pytest --huly --huly-project="My Project" --huly-run-name="Manual Verification Run"`.
- [ ] Verify console reports successful test execution and Huly sync.
- [ ] Open Huly Web UI -> `Test Management` -> `My Project` -> `Test Runs`:
  - Verify "Manual Verification Run" appears with correct timestamp and total test count.
  - Open the run. Verify all passed, failed, and skipped test cases match Pytest output.
  - Open a failed test result. Verify the failure stack trace and assertion error are rendered in the description pane.

---

# 7. Conclusion

This synthesis establishes an end-to-end architectural blueprint for Huly's four major capability expansions. By leveraging Huly's native primitives—the Transactor 26-step pipeline, partitioned domain storage in CockroachDB, Svelte plugin contracts, LiveKit SFU Dynacast/Simulcast engines, and Y.js CRDT synchronization—each feature is implemented with **minimal new abstractions, maximum performance, and complete backward compatibility**.
