# Research & Implementation Specification: Meeting Multi-Screen Sharing in Huly

## 1. Executive Summary

Huly's virtual office and meeting subsystem ("Love") is powered by [LiveKit](https://livekit.io), utilizing WebRTC for ultra-low-latency audio, video, and screen sharing. While the underlying LiveKit SFU (Selective Forwarding Unit) and server architecture natively support simultaneous publishing of arbitrary video tracks (including multiple `Track.Source.ScreenShare` tracks from multiple participants or multiple displays from a single participant), Huly currently restricts meetings to a **single presenter / single screen stream**.

This restriction is not a LiveKit protocol or SFU limitation; it is entirely enforced by **client-side state management, UI gating logic, and a single-track video rendering layout** in `plugins/love-resources`.

This document provides a comprehensive analysis of the existing codebase, identifies all architectural bottlenecks preventing multi-screen sharing, and specifies the exact state models, API modifications, and Svelte UI refactorings required to support:
1. **Simultaneous multi-user screen sharing** (multiple participants sharing screens at the same time).
2. **Multiple display shares per user** (a single participant sharing multiple monitors or application windows simultaneously).
3. **Flexible presentation layouts** (Side-by-Side, 2x2 Grid, and Stage + Presenter Carousel).

---

## 2. Current Architecture & Codebase Inspection

### 2.1 Component Topology

The meeting system in Huly resides across three primary areas:
- **`plugins/love-resources`**: Frontend meeting UI, LiveKit client wrapper, Svelte stores, and WebRTC media lifecycle.
- **`desktop/src/ui/screenShare.ts`**: Electron desktop capture hooks overriding `navigator.mediaDevices.getDisplayMedia` and LiveKit's `createScreenTracks`.
- **`services/love`**: Backend Node.js microservice managing LiveKit rooms, JWT tokens, and egress/recording.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Huly Meeting Architecture                         │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
         ┌─────────────────────────┴─────────────────────────┐
         ▼                                                   ▼
┌───────────────────────────────────┐       ┌───────────────────────────────────┐
│        Desktop (Electron)         │       │          Web Browser              │
│    `desktop/src/ui/screenShare.ts`│       │  `plugins/love-resources`         │
│  - getScreenSources() (IPC)       │       │  - navigator.mediaDevices         │
│  - SelectScreenSourcePopup        │       │    .getDisplayMedia()             │
│  - custom createScreenTracks      │       │                                   │
└─────────────────┬─────────────────┘       └─────────────────┬─────────────────┘
                  │                                           │
                  └─────────────────────┬─────────────────────┘
                                        ▼
                   ┌────────────────────────────────────────┐
                   │    plugins/love-resources              │
                   │    `LiveKitClient` (liveKitClient.ts)  │
                   │    - LKRoom instance                   │
                   │    - screenSharingState (tri-state)    │
                   │    - localParticipant.setScreenShare   │
                   └────────────────────┬───────────────────┘
                                        │
         ┌──────────────────────────────┼──────────────────────────────┐
         ▼                              ▼                              ▼
┌─────────────────────────┐ ┌─────────────────────────┐ ┌─────────────────────────┐
│ ScreenSharingView.svelte│ │ ShareScreenButton.svelte│ │      Room.svelte        │
│ - Single <video> element│ │ - disabled when Remote  │ │ - Binary layout         │
│ - Single activeTrack    │ │ - Binary toggle         │ │ - Fixed 15rem sidebar   │
│ - Breaks on 1st match   │ │                         │ │   when sharing=true     │
└─────────────────────────┘ └─────────────────────────┘ └─────────────────────────┘
```

### 2.2 LiveKit Server Token & SFU Capabilities (`services/love/src/main.ts`)

In `services/love/src/main.ts`:
```typescript
const createToken = async (roomName: string, _id: string, participantName: string): Promise<string> => {
  const at = new AccessToken(config.ApiKey, config.ApiSecret, {
    identity: _id,
    name: participantName,
    ttl: '10m'
  })
  at.addGrant({ roomJoin: true, room: roomName })
  return await at.toJwt()
}
```
**Finding**: The token grant explicitly allows `roomJoin: true` without constraining `canPublish`, `canSubscribe`, or `canPublishSources`. LiveKit server defaults to permitting all track publications, including multiple video tracks and multiple screen shares. **The backend imposes zero restrictions on multi-screen sharing.**

---

## 3. Root Cause Analysis: Why Screen Sharing is Restricted

Our deep-dive into `plugins/love-resources` identified **five concrete bottlenecks** that lock Huly into a single-presenter model:

### 3.1 Bottleneck 1: Tri-State Enum Bottleneck (`plugins/love-resources/src/liveKitClient.ts`)

`liveKitClient.ts` defines screen sharing as a scalar tri-state:
```typescript
export enum ScreenSharingState {
  Inactive,
  Local,
  Remote
}
export const screenSharingState = writable<ScreenSharingState>(ScreenSharingState.Inactive)
```
In event listeners:
```typescript
onTrackSubscribed = (track: RemoteTrack, ...): void => {
  if (track.kind === Track.Kind.Video && track.source === Track.Source.ScreenShare) {
    screenSharingState.set(ScreenSharingState.Remote)
  }
}

onTrackUnsubscribed = (track: RemoteTrack, ...): void => {
  if (track.kind === Track.Kind.Video && track.source === Track.Source.ScreenShare) {
    screenSharingState.set(ScreenSharingState.Inactive)
  }
}

onLocalTrackPublished = (publication: LocalTrackPublication, ...): void => {
  if (publication.track?.kind === Track.Kind.Video && publication.track.source === Track.Source.ScreenShare) {
    session?.setFeature('sharing', { enabled: true, track, deviceId })
    screenSharingState.set(ScreenSharingState.Local)
  }
}

onLocalTrackUnpublished = (publication: LocalTrackPublication, ...): void => {
  if (publication.track?.kind === Track.Kind.Video && publication.track.source === Track.Source.ScreenShare) {
    session?.setFeature('sharing', { enabled: false })
    screenSharingState.set(ScreenSharingState.Inactive)
  }
}
```

#### Fatal Flaws:
1. **Collision of Local and Remote**: If User A is sharing locally (`Local`), and User B publishes a screen share, `onTrackSubscribed` fires on User A's client and overwrites `screenSharingState` to `Remote`, breaking User A's local UI state.
2. **Race condition on track departure**: If User B and User C are both sharing remotely, and User B stops, `onTrackUnsubscribed` unconditionally sets `screenSharingState.set(ScreenSharingState.Inactive)`, even though User C is still actively sharing!
3. **No support for multiple streams per participant**: A participant can only be recorded as sharing or not sharing; individual tracks are not tracked.

---

### 3.2 Bottleneck 2: Hard-Coded UI Disabling (`ShareScreenButton.svelte` & `SharingStateIndicator.svelte`)

In `plugins/love-resources/src/components/meeting/controls/ShareScreenButton.svelte` (line 34):
```svelte
<SplitButton
  ...
  disabled={$screenSharingState === ScreenSharingState.Remote || !$lkSessionConnected}
  action={changeShare}
/>
```
- When any participant begins sharing, `$screenSharingState` transitions to `Remote` for all other participants.
- **The UI explicitly disables the screen share button for everyone else.**
- Furthermore, `changeShare` toggles sharing via `const newValue = $screenSharingState !== ScreenSharingState.Local`, which assumes a user can only toggle their single share on or off.

In `plugins/love-resources/src/components/SharingStateIndicator.svelte` (line 35):
```svelte
function handleShare (): void {
  if ($screenSharingState !== ScreenSharingState.Inactive) return
  void liveKitClient.setScreenShareEnabled(true, $isShareWithSound)
}
```
- Re-sharing is explicitly aborted if the state is anything other than `Inactive`.

---

### 3.3 Bottleneck 3: Single-Video Element & Early Loop Break (`ScreenSharingView.svelte`)

In `plugins/love-resources/src/components/meeting/ScreenSharingView.svelte`:
```svelte
<script lang="ts">
  export let hasActiveTrack: boolean = false
  export let showLocalTrack: boolean = true

  let activeTrack: Track | null = null
  let screen: HTMLVideoElement

  function trySetActiveTrack (track: Track | undefined): boolean {
    if (track === undefined) return false
    if (track.kind !== Track.Kind.Video || track.source !== Track.Source.ScreenShare) return false
    hasActiveTrack = true
    activeTrack = track
    track.attach(screen)
    return true
  }

  onMount(async () => {
    ...
    for (const participant of lk.remoteParticipants.values()) {
      for (const publication of participant.trackPublications.values()) {
        if (trySetActiveTrack(publication.track)) break  // <--- BREAKS ON FIRST TRACK!
      }
    }
    if (showLocalTrack) {
      for (const publication of lk.localParticipant.trackPublications.values()) {
        if (trySetActiveTrack(publication.track)) break  // <--- BREAKS ON FIRST TRACK!
      }
    }
  })
</script>

<video class="screen" bind:this={screen}></video>
```
#### Fatal Flaws:
1. **Only One `<video>` Tag**: The template only contains a single `<video class="screen">` tag.
2. **First-Come, First-Served**: The loop in `onMount` breaks on the very first screen share track it encounters. Any subsequent screen share tracks published by other users or the same user are dropped.
3. **No Presenter Identification**: There is no UI rendering the presenter's avatar, name, or source window/monitor title on top of the screen share.
4. **Detachment Bug**: When `onTrackUnsubscribed` is received for the active track, it detaches and sets `hasActiveTrack = false`, completely failing to promote another still-active screen track.

---

### 3.4 Bottleneck 4: Binary Room Container Layout (`Room.svelte`)

In `plugins/love-resources/src/components/Room.svelte`:
```svelte
<div
  class="room-container"
  class:sharing={withScreenSharing}
  ...
>
  <div class="screenContainer">
    <ScreenSharingView bind:hasActiveTrack={withScreenSharing} />
  </div>
  <div class="videoGrid" style={withScreenSharing ? '' : gridStyle} class:scroll-m-0={withScreenSharing}>
    <ParticipantsListView ... />
  </div>
</div>
```
CSS styles in `Room.svelte`:
```scss
.room-container {
  &:not(.sharing) {
    .videoGrid {
      display: grid;
      grid-auto-rows: 1fr;
      /* Dynamic multi-column layout for participant webcams */
    }
    .screenContainer {
      display: none;
    }
  }
  &.sharing {
    gap: 1rem;
    .screenContainer {
      width: 100%;
      /* Assumes 1 single presentation taking the full container */
    }
    .videoGrid {
      width: 15rem;
      min-width: 15rem;
      flex-direction: column;
      overflow-y: auto;
      /* Shrinks webcams into a narrow 15rem right sidebar */
    }
  }
}
```
- `withScreenSharing` is a boolean flag (`hasActiveTrack`).
- The entire layout assumes:
  - `false`: grid of participant webcams.
  - `true`: 1 large screen share + 1 vertical sidebar of webcams.
- It provides no layout container for multiple screen shares (e.g. splitting the main stage into 2 columns, a 2x2 grid, or tabbed views).

---

### 3.5 Bottleneck 5: Single Screen Share Track API in LiveKit Client & Electron

In `plugins/love-resources/src/liveKitClient.ts`:
```typescript
async setScreenShareEnabled (value: boolean, withAudio: boolean = false): Promise<void> {
  try {
    await this.liveKitRoom.localParticipant.setScreenShareEnabled(value, { audio: withAudio })
  } catch (e) {
    console.log(e)
  }
}
```
- In LiveKit JS SDK, `LocalParticipant.setScreenShareEnabled` is a convenience method that only manages **a single screen share track** (`source: Track.Source.ScreenShare`).
- If a user calls `setScreenShareEnabled(true)` when already sharing, it either re-prompts or stops the existing share.
- To publish multiple screens (e.g. Monitor 1 and Monitor 2 simultaneously), the application must call `localParticipant.publishTrack(localTrack, { source: Track.Source.ScreenShare, name: trackName })`.
- In `desktop/src/ui/screenShare.ts`, `SelectScreenSourcePopup.svelte` only allows choosing one source ID from Electron's `desktopCapturer.getSources()`.

---

## 4. Implementation Specification for Multi-Screen Sharing

To achieve multi-screen sharing, we divide the implementation into four core phases:
1. **Multi-Track Data Model & Reactive Stores**
2. **LiveKitClient Track Management Refactoring**
3. **Responsive UI Layouts & Presenter Carousel (`ScreenSharingView.svelte`)**
4. **Control Bar & Source Selection (`ShareScreenButton.svelte`, Electron)**

---

### 4.1 Phase 1: Multi-Track Data Model & Reactive Stores

#### New Types (`plugins/love-resources/src/types.ts`)
```typescript
import { Track, TrackPublication, Participant } from 'livekit-client'

export interface ActiveScreenShare {
  id: string                    // unique ID (publication.trackSid || localTrack.id)
  track: Track
  publication: TrackPublication
  participant: Participant
  isLocal: boolean
  sourceName?: string           // e.g. "Screen 1", "Visual Studio Code"
  displaySurface?: 'monitor' | 'window' | 'browser'
}

export type ScreenShareLayoutMode = 'auto' | 'grid' | 'focused' | 'side-by-side'
```

#### New Reactive Stores (`plugins/love-resources/src/stores.ts`)
Replace the scalar `screenSharingState` with collection-based stores:

```typescript
import { writable, derived, type Readable } from 'svelte/store'
import type { ActiveScreenShare, ScreenShareLayoutMode } from './types'

// Map of trackSid -> ActiveScreenShare
export const activeScreenShares = writable<Map<string, ActiveScreenShare>>(new Map())

// Primary focused screen share ID (null = automatic grid/side-by-side)
export const focusedScreenShareId = writable<string | null>(null)

// Preferred layout mode
export const screenShareLayoutMode = writable<ScreenShareLayoutMode>('auto')

// Derived helpers
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

// Backward compatibility helper for components still expecting ScreenSharingState enum
export const screenSharingState: Readable<ScreenSharingState> = derived(
  [isLocalScreenSharing, hasActiveScreenShares],
  ([$isLocal, $hasActive]) => {
    if ($isLocal) return ScreenSharingState.Local
    if ($hasActive) return ScreenSharingState.Remote
    return ScreenSharingState.Inactive
  }
)
```

---

### 4.2 Phase 2: LiveKitClient Track Management Refactoring (`plugins/love-resources/src/liveKitClient.ts`)

Refactor `LiveKitClient` to maintain the `activeScreenShares` map across all room events:

```typescript
import { activeScreenShares, focusedScreenShareId } from './stores'
import type { ActiveScreenShare } from './types'

export class LiveKitClient {
  // ... existing fields ...

  private registerScreenTrack(
    track: Track,
    publication: TrackPublication,
    participant: Participant,
    isLocal: boolean
  ): void {
    if (track.kind !== Track.Kind.Video || publication.source !== Track.Source.ScreenShare) {
      return
    }

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

    // Reset focused screen if the focused track was removed
    focusedScreenShareId.update((current) => (current === id ? null : current))
  }

  onTrackSubscribed = (
    track: RemoteTrack,
    publication: RemoteTrackPublication,
    participant: RemoteParticipant
  ): void => {
    if (track.kind === Track.Kind.Video && track.source === Track.Source.ScreenShare) {
      this.registerScreenTrack(track, publication, participant, false)
    }
  }

  onTrackUnsubscribed = (
    track: RemoteTrack,
    publication: RemoteTrackPublication,
    participant: RemoteParticipant
  ): void => {
    if (track.kind === Track.Kind.Video && track.source === Track.Source.ScreenShare) {
      this.unregisterScreenTrack(publication)
    }
  }

  onLocalTrackPublished = (
    publication: LocalTrackPublication,
    participant: LocalParticipant
  ): void => {
    if (publication.track?.kind === Track.Kind.Video && publication.source === Track.Source.ScreenShare) {
      this.registerScreenTrack(publication.track, publication, participant, true)
      this.currentMediaSession?.setFeature('sharing', {
        enabled: true,
        track: publication.track.mediaStreamTrack,
        deviceId: publication.track.mediaStreamTrack?.getSettings().deviceId
      })
    }
    // ... camera and mic handlers ...
  }

  onLocalTrackUnpublished = (
    publication: LocalTrackPublication,
    _participant: LocalParticipant
  ): void => {
    if (publication.source === Track.Source.ScreenShare) {
      this.unregisterScreenTrack(publication)
      if (get(localScreenShares).length === 0) {
        this.currentMediaSession?.setFeature('sharing', { enabled: false })
      }
    }
  }

  /**
   * Publish an additional screen share (supports multi-display per user)
   */
  async publishAdditionalScreenShare(
    customTracks?: Array<LocalTrack>
  ): Promise<LocalTrackPublication | undefined> {
    try {
      let tracks = customTracks
      if (!tracks) {
        tracks = await createScreenTracks({
          audio: false,
          resolution: ScreenSharePresets.h1080fps30.resolution
        })
      }
      const videoTrack = tracks.find((t) => t.kind === Track.Kind.Video)
      if (videoTrack) {
        const publication = await this.liveKitRoom.localParticipant.publishTrack(videoTrack, {
          source: Track.Source.ScreenShare,
          name: `screen-${Date.now()}`
        })
        return publication
      }
    } catch (err) {
      console.error('Failed to publish additional screen share:', err)
      throw err
    }
  }

  /**
   * Stop a specific screen share by trackSid
   */
  async stopScreenShare(trackSid: string): Promise<void> {
    const pub = this.liveKitRoom.localParticipant.getTrackPublication(trackSid)
    if (pub?.track) {
      await this.liveKitRoom.localParticipant.unpublishTrack(pub.track, true)
    }
  }

  /**
   * Stop all local screen shares
   */
  async stopAllScreenShares(): Promise<void> {
    const pubs = this.liveKitRoom.localParticipant.getTrackPublications()
    for (const pub of pubs) {
      if (pub.source === Track.Source.ScreenShare && pub.track) {
        await this.liveKitRoom.localParticipant.unpublishTrack(pub.track, true)
      }
    }
  }
}
```

---

### 4.3 Phase 3: Svelte UI Refactoring (`ScreenSharingView.svelte`)

Instead of rendering a single `<video>` element, `ScreenSharingView.svelte` must dynamically manage video elements for each active track, support dynamic grid layouts, and provide presenter badges.

#### Layout Strategy:
- **1 Screen Share**: Full size (100% width/height, `object-fit: contain`).
- **2 Screen Shares**: 2-column side-by-side split (`grid-template-columns: repeat(2, 1fr)`).
- **3-4 Screen Shares**: 2x2 grid (`grid-template-columns: repeat(2, 1fr); grid-template-rows: repeat(2, 1fr)`).
- **Stage + Presenter Filmstrip Mode (when `focusedScreenShareId` is active or >4 shares)**:
  - Top/Center Stage: Focused screen share with priority aspect ratio.
  - Bottom Bar (Filmstrip): Thumbnails of all other screen shares with presenter names and live previews. Clicking a thumbnail focuses that presenter's screen.

#### Refactored `ScreenSharingView.svelte` Component Implementation:
```svelte
<script lang="ts">
  import { onDestroy } from 'svelte'
  import {
    screenSharesList,
    focusedScreenShareId,
    screenShareLayoutMode
  } from '../../stores'
  import type { ActiveScreenShare } from '../../types'
  import ScreenTile from './ScreenTile.svelte'
  import ScreenFilmstrip from './ScreenFilmstrip.svelte'

  export let hasActiveTrack: boolean = false
  export let showLocalTrack: boolean = true

  $: visibleShares = $screenSharesList.filter((s) => showLocalTrack || !s.isLocal)
  $: hasActiveTrack = visibleShares.length > 0

  $: activeFocus = $focusedScreenShareId
    ? visibleShares.find((s) => s.id === $focusedScreenShareId) ?? visibleShares[0]
    : null

  $: layout = $screenShareLayoutMode === 'auto'
    ? (visibleShares.length > 2 || $focusedScreenShareId ? 'focused' : 'grid')
    : $screenShareLayoutMode
</script>

{#if visibleShares.length === 0}
  <div class="empty-state">No active screen shares</div>
{:else if layout === 'grid' || visibleShares.length === 1}
  <div
    class="screens-grid"
    class:single={visibleShares.length === 1}
    class:split={visibleShares.length === 2}
    class:quad={visibleShares.length >= 3}
  >
    {#each visibleShares as share (share.id)}
      <ScreenTile
        {share}
        on:focus={() => focusedScreenShareId.set(share.id)}
      />
    {/each}
  </div>
{:else if layout === 'focused' && activeFocus}
  <div class="focused-layout">
    <div class="main-stage">
      <ScreenTile
        share={activeFocus}
        isStage={true}
        on:unfocus={() => focusedScreenShareId.set(null)}
      />
    </div>
    {#if visibleShares.length > 1}
      <div class="filmstrip-container">
        <ScreenFilmstrip
          shares={visibleShares}
          focusedId={activeFocus.id}
          on:select={(e) => focusedScreenShareId.set(e.detail)}
        />
      </div>
    {/if}
  </div>
{/if}

<style lang="scss">
  .screens-grid {
    display: grid;
    width: 100%;
    height: 100%;
    gap: 0.75rem;
    align-items: center;
    justify-content: center;

    &.single {
      grid-template-columns: 1fr;
      grid-template-rows: 1fr;
    }
    &.split {
      grid-template-columns: 1fr 1fr;
      grid-template-rows: 1fr;
    }
    &.quad {
      grid-template-columns: 1fr 1fr;
      grid-template-rows: 1fr 1fr;
    }
  }

  .focused-layout {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    gap: 0.5rem;

    .main-stage {
      flex: 1;
      min-height: 0;
      position: relative;
    }

    .filmstrip-container {
      height: 6rem;
      flex-shrink: 0;
    }
  }
</style>
```

#### New Subcomponent: `ScreenTile.svelte`
Attaches the individual LiveKit `Track` to an isolated `<video>` element, handles track attach/detach lifecycle safely, and renders the presenter's name badge, avatar, and display surface info:

```svelte
<script lang="ts">
  import { onMount, onDestroy, createEventDispatcher } from 'svelte'
  import { Avatar } from '@hcengineering/contact-resources'
  import { Button, Icon, IconMaximize, IconMinimize } from '@hcengineering/ui'
  import type { ActiveScreenShare } from '../../types'
  import { liveKitClient } from '../../utils'

  export let share: ActiveScreenShare
  export let isStage: boolean = false

  const dispatch = createEventDispatcher()
  let videoEl: HTMLVideoElement
  let isTileFullscreen = false

  onMount(() => {
    share.track.attach(videoEl)
  })

  onDestroy(() => {
    share.track.detach(videoEl)
  })

  function toggleTileFullscreen(): void {
    if (!document.fullscreenElement) {
      videoEl.requestFullscreen?.()
      isTileFullscreen = true
    } else {
      document.exitFullscreen?.()
      isTileFullscreen = false
    }
  }
</script>

<div class="screen-tile" class:stage={isStage}>
  <video bind:this={videoEl} autoplay playsinline muted={share.isLocal}></video>

  <!-- Presenter Info Overlay Badge -->
  <div class="tile-header">
    <div class="presenter-badge">
      <span class="name">{share.participant.name}</span>
      {#if share.displaySurface}
        <span class="surface">({share.displaySurface})</span>
      {/if}
      {#if share.isLocal}
        <span class="tag local">You</span>
      {/if}
    </div>

    <div class="tile-controls">
      {#if !isStage}
        <button class="action-btn" on:click={() => dispatch('focus')}>Focus</button>
      {:else}
        <button class="action-btn" on:click={() => dispatch('unfocus')}>Grid View</button>
      {/if}
      <button class="action-btn" on:click={toggleTileFullscreen}>
        <Icon icon={isTileFullscreen ? IconMinimize : IconMaximize} size="small" />
      </button>
      {#if share.isLocal}
        <button class="action-btn stop" on:click={() => liveKitClient.stopScreenShare(share.id)}>
          Stop
        </button>
      {/if}
    </div>
  </div>
</div>

<style lang="scss">
  .screen-tile {
    position: relative;
    width: 100%;
    height: 100%;
    background: #0f1115;
    border-radius: 0.75rem;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;

    video {
      width: 100%;
      height: 100%;
      object-fit: contain;
    }

    .tile-header {
      position: absolute;
      top: 0.5rem;
      left: 0.5rem;
      right: 0.5rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: rgba(0, 0, 0, 0.6);
      padding: 0.35rem 0.6rem;
      border-radius: 0.5rem;
      backdrop-filter: blur(8px);

      .presenter-badge {
        display: flex;
        align-items: center;
        gap: 0.4rem;
        font-size: 0.85rem;
        color: #fff;

        .surface {
          color: #aaa;
          font-size: 0.75rem;
        }

        .tag.local {
          background: var(--primary-accent, #3b82f6);
          padding: 0.1rem 0.35rem;
          border-radius: 0.25rem;
          font-size: 0.7rem;
        }
      }

      .tile-controls {
        display: flex;
        gap: 0.4rem;

        .action-btn {
          background: rgba(255, 255, 255, 0.15);
          color: white;
          border: none;
          padding: 0.2rem 0.5rem;
          border-radius: 0.3rem;
          cursor: pointer;
          font-size: 0.75rem;

          &:hover {
            background: rgba(255, 255, 255, 0.25);
          }

          &.stop {
            background: var(--bg-negative-default, #ef4444);
          }
        }
      }
    }
  }
</style>
```

---

### 4.4 Phase 4: Control Bar & Multi-Screen Source Selection

#### Refactored `ShareScreenButton.svelte`
Remove the disabling condition when someone else is sharing, and add a dropdown menu when already sharing to allow sharing an additional monitor or stopping specific screens:

```svelte
<script lang="ts">
  import { SplitButton, showPopup, eventToHTMLElement } from '@hcengineering/ui'
  import { isShareWithSound, liveKitClient } from '../../../utils'
  import {
    lkSessionConnected,
    isLocalScreenSharing,
    localScreenShares
  } from '../../../stores'
  import ShareMultiScreenMenuPopup from '../../ShareMultiScreenMenuPopup.svelte'

  export let size = 'large'

  async function togglePrimaryShare(): Promise<void> {
    if ($isLocalScreenSharing) {
      await liveKitClient.stopAllScreenShares()
    } else {
      await liveKitClient.publishAdditionalScreenShare()
    }
  }

  function openShareMenu(e: MouseEvent): void {
    showPopup(ShareMultiScreenMenuPopup, {}, eventToHTMLElement(e))
  }
</script>

<SplitButton
  {size}
  icon={$isLocalScreenSharing ? love.icon.SharingEnabled : love.icon.SharingDisabled}
  iconProps={{
    fill: $isLocalScreenSharing ? 'var(--bg-negative-default)' : 'var(--bg-positive-default)'
  }}
  showTooltip={{ label: $isLocalScreenSharing ? love.string.StopShare : love.string.Share }}
  disabled={!$lkSessionConnected} <!-- REMOVED: screenSharingState === Remote! -->
  action={togglePrimaryShare}
  secondIcon={love.icon.CaretDown}
  secondAction={openShareMenu}
  separate
/>
```

#### New Popup: `ShareMultiScreenMenuPopup.svelte`
Provides an interactive menu:
- **Share Another Screen / Window**: Opens source picker without interrupting existing shares.
- **Active Shares List**: Displays each local share with its surface type and a dedicated "Stop" button.
- **Audio Toggle**: Checkbox for "Share System Audio".

---

### 4.5 Phase 5: Room Layout Responsiveness (`Room.svelte`)

When multiple screens are shared, room real estate is at a premium:
- In `Room.svelte`, when `$screenSharesList.length >= 2`:
  - Provide a toggle in the meeting control bar between **Grid** and **Stage + Filmstrip**.
  - Provide a button to collapse the right participant video sidebar (`videoGrid`) into a minimized floating avatar bar, giving maximum width to the dual screens.
  - Dynamically recalculate aspect ratios so two 16:9 displays fit side-by-side without letterboxing.

---

## 5. Summary of Required File Changes

| File Path | Nature of Change | Purpose |
|---|---|---|
| `plugins/love-resources/src/types.ts` | **Add** | Add `ActiveScreenShare` and `ScreenShareLayoutMode` interfaces. |
| `plugins/love-resources/src/stores.ts` | **Modify** | Replace scalar `screenSharingState` with `activeScreenShares`, `focusedScreenShareId`, and derived helpers. |
| `plugins/love-resources/src/liveKitClient.ts` | **Modify** | Maintain map of active screen tracks on `TrackSubscribed`/`Unsubscribed`; implement `publishAdditionalScreenShare()`, `stopScreenShare()`, `stopAllScreenShares()`. |
| `plugins/love-resources/src/components/meeting/ScreenSharingView.svelte` | **Rewrite** | Replace single `<video>` element with dynamic multi-video layout (Side-by-Side, Quad Grid, Stage + Filmstrip). |
| `plugins/love-resources/src/components/meeting/ScreenTile.svelte` | **New** | Individual screen video tile with presenter badge, surface label, focus toggle, and fullscreen control. |
| `plugins/love-resources/src/components/meeting/ScreenFilmstrip.svelte` | **New** | Thumbnail bar for switching focused presenter in multi-share meetings. |
| `plugins/love-resources/src/components/meeting/controls/ShareScreenButton.svelte` | **Modify** | Remove `disabled` check on remote shares; support split button for multi-share management. |
| `plugins/love-resources/src/components/ShareMultiScreenMenuPopup.svelte` | **New** | Dropdown popup for adding another display share or stopping individual displays. |
| `plugins/love-resources/src/components/SharingStateIndicator.svelte` | **Modify** | Allow starting share when remote shares exist; indicate number of active local shares. |
| `plugins/love-resources/src/components/Room.svelte` | **Modify** | Adapt layout classes to handle multiple screen aspect ratios; allow collapsing webcam sidebar. |
| `desktop/src/ui/screenShare.ts` | **Modify** | Support selecting and publishing multiple screens sequentially without overriding existing track. |

---

## 6. Verification and Validation Checklist

To manually verify the multi-screen sharing implementation once built:
1. **Multi-User Concurrency**:
   - Connect User A and User B to the same room.
   - User A starts screen sharing. Verify User B can see User A's screen.
   - Verify User B's "Share Screen" button remains enabled.
   - User B clicks "Share Screen".
   - Verify both User A and User B screens appear side-by-side on both clients with correct presenter name overlays.
2. **Single User Multi-Display**:
   - User A connects on desktop with two monitors.
   - User A shares Display 1.
   - User A clicks the share menu and selects "Share Another Screen", picking Display 2.
   - Verify both Display 1 and Display 2 are published and displayed in the room grid.
3. **Presenter Focus Mode**:
   - With 3 screen shares active, click "Focus" on User A's screen.
   - Verify User A's screen occupies the main stage, and User B's screen and Display 2 appear in the bottom filmstrip.
   - Click User B's thumbnail; verify the stage smoothly updates to User B's screen.
4. **Graceful Disconnection**:
   - Stop one of the three shares.
   - Verify the remaining two shares seamlessly transition into side-by-side view without freezing or black screen.
   - Disconnect User B; verify User B's screen cleanly disappears and layout scales to single share.
