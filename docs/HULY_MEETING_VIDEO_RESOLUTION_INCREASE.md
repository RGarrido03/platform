# Research & Implementation Specification: Increasing Video & Screen Share Resolution in Huly Meetings

## 1. Executive Summary

Huly's virtual office meeting subsystem ("Love") currently publishes camera video at **720p (1280x720 @ 30fps)** and screen sharing capped at **15fps** (with desktop defaulting to 1080p30). As modern displays (1440p, 4K, 5K Retina) and high-resolution webcams (1080p, 4K) become ubiquitous, 720p camera video and 15fps screen sharing result in noticeable softness, text blurriness during IDE/code sharing, and choppy animations during product demonstrations.

This document details:
1. Current video capture presets, encodings, and constraints in `plugins/love-resources`, `desktop/src/ui/screenShare.ts`, and `services/love`.
2. LiveKit SFU server configuration, bandwidth/bitrate limits, and multi-codec optimization (VP9 SVC, AV1, H.264).
3. Client-side trade-offs (CPU vs Bandwidth vs Battery), dynamic resolution adaptation via **Simulcast**, **Dynacast**, and **AdaptiveStream**.
4. User-facing UI controls in `CamSettingPopup.svelte` and `ShareSettingPopup.svelte` for selecting video and screen share quality presets (e.g. 720p, 1080p, 1440p, 4K).
5. Exact code changes, types, preference extensions, and configuration parameters across client and server.

---

## 2. Current Video & Encoding Baseline Analysis

### 2.1 Client Video Capture & Room Defaults (`plugins/love-resources/src/liveKitClient.ts`)

In `plugins/love-resources/src/liveKitClient.ts`:
```typescript
const defaultCaptureOptions: VideoCaptureOptions = {
  facingMode: 'user',
  resolution: {
    width: 1280,
    height: 720,
    frameRate: 30
  }
}

export class LiveKitClient {
  constructor () {
    const lkRoom = new LKRoom({
      adaptiveStream: true,
      dynacast: true,
      publishDefaults: {
        videoCodec: 'vp9',
        screenShareEncoding: {
          maxBitrate: 7_000_000,
          maxFramerate: 15,
          priority: 'high'
        }
      },
      // ...
      videoCaptureDefaults: defaultCaptureOptions
    })
    // ...
  }
}
```

#### Key Findings:
1. **Camera Resolution Capped to 720p**: `videoCaptureDefaults` specifies hardcoded `1280x720` at 30 fps. Even if the user connects an external 1080p or 4K webcam (e.g. Logitech Brio, Insta360 Link, Apple Continuity Camera), `getUserMedia` is constrained to 720p.
2. **Missing `videoEncoding` in `publishDefaults`**: While `screenShareEncoding` is defined, camera `videoEncoding` is omitted. LiveKit SDK falls back to internal defaults (~1.5 Mbps for 720p). If 1080p capture were enabled without adjusting `videoEncoding`, the publisher would suffer from severe compression artifacts due to insufficient bitrate.
3. **Screen Share Framerate Capped to 15fps**: `screenShareEncoding.maxFramerate` is set to `15`. While 15fps reduces bandwidth for static documents, it introduces severe stutter when presenting Figma designs, browser animations, video playback, or scrolling fast.
4. **Desktop Screen Capture Resolution (`desktop/src/ui/screenShare.ts`)**:
   ```typescript
   if (options.resolution === undefined) {
     options.resolution = ScreenSharePresets.h1080fps30.resolution
   }
   ```
   Electron screen sharing defaults to 1080p (`1920x1080`), but web browser screen sharing relies on browser defaults or 15fps presets without offering 1440p (2K) or 4K options.

---

### 2.2 Server Recording & Egress Presets (`services/love/src/preset.ts`)

In `services/love/src/preset.ts`:
```typescript
export const RecordingPreset720p: RecordingPreset = {
  name: '720p',
  width: 1280,
  height: 720,
  preset: EncodingOptionsPreset.H264_720P_30
}

export const RecordingPreset1080p: RecordingPreset = {
  name: '1080p',
  width: 1920,
  height: 1080,
  preset: EncodingOptionsPreset.H264_1080P_30
}

export function getRecordingPreset (name: string | undefined): RecordingPreset {
  switch (name) {
    case RecordingPreset1080p.name:
      return RecordingPreset1080p
    default:
      return RecordingPreset720p
  }
}
```
- Egress recording defaults to `RecordingPreset720p` unless `RECORDING_PRESET=1080p` is provided in environment variables.
- There are no presets for 1440p or 4K egress/recording.

---

### 2.3 User Preferences (`plugins/love/src/types.ts` & `plugins/love-resources/src/stores.ts`)

In `plugins/love/src/types.ts`:
```typescript
export interface DevicesPreference extends Preference {
  micEnabled: boolean
  noiseCancellation: boolean
  blurRadius: number
  camEnabled: boolean
}
```
- `DevicesPreference` currently stores only microphone, camera enable state, blur, and noise cancellation.
- There are no persisted settings for camera resolution, screen share quality, or preference for motion vs. detail.

---

## 3. Architecture for Higher Video & Screen Share Resolution

### 3.1 Resolving the Bandwidth vs Quality Conflict

Increasing resolution from 720p to 1080p quadruples pixel count from 0.92 MP to 2.07 MP. Upgrading to 4K (3840x2160) multiplies pixels by 8.3x (8.29 MP). If all participants published 1080p/4K directly without adaptation, rooms with 5+ participants would quickly saturate CPU and network bandwidth (especially upstream for publishers and downstream for mobile/laptop participants).

To solve this, Huly must leverage LiveKit's **three-tier adaptation engine**:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     Three-Tier Adaptation Engine                         │
└─────────────────────────────────────────────────────────────────────────┘
   1. SIMULCAST (Publisher)
      Publish 3 spatial layers:
      ├── High Layer:   1080p @ 3.0 Mbps  (or 4K @ 8.0 Mbps for screen share)
      ├── Medium Layer:  540p @ 800 kbps  (or 1080p @ 2.5 Mbps)
      └── Low Layer:     270p @ 180 kbps  (or 540p @ 500 kbps)
                                    │
                                    ▼
   2. SFU DYNACAST (LiveKit Server)
      SFU monitors subscribers:
      ├── Are subscribers requesting High layer? -> Keep High layer active
      └── If NO subscriber needs High layer -> Signal publisher to PAUSE High layer!
          (Saves 70% publisher upload bandwidth and encoding CPU)
                                    │
                                    ▼
   3. ADAPTIVE STREAM (Subscriber Client)
      Inspects DOM element rendered dimensions:
      ├── Participant in 15rem sidebar (width ~240px) -> Subscribes to LOW layer
      ├── Participant in 2x2 grid (width ~600px)     -> Subscribes to MEDIUM layer
      └── Participant focused/fullscreen (>1200px)   -> Subscribes to HIGH layer
```

Fortunately, `adaptiveStream: true` and `dynacast: true` are **already instantiated** in `LiveKitClient`'s constructor! However, they are underutilized because:
1. `videoCaptureDefaults` forces 720p capture.
2. Explicit `simulcast` layers and presets are not parameterized on `publishDefaults`.
3. Screen share does not enable simulcast by default, causing 4K screen shares to blast full bitrates to all subscribers.

---

### 3.2 Video Codec Strategy: VP9, AV1, and H.264

Huly's `LiveKitClient` sets `videoCodec: 'vp9'`. This is a strong default, but we should refine how it operates:

1. **VP9 with SVC (Scalable Video Coding)**:
   - VP9 supports spatial and temporal scalability in a single WebRTC track (K-SVC, e.g. `L3T3_KEY`).
   - Instead of encoding three separate simulcast bitstreams (which takes extra CPU), VP9 SVC encodes a single base stream with enhancement layers.
   - For 1080p camera video, VP9 SVC achieves 30% lower bitrate than H.264 at identical perceptual quality.
2. **AV1 for Screen Sharing (1080p / 1440p / 4K)**:
   - Screen shares consist of sharp fonts, high-contrast UI elements, and solid color backgrounds.
   - AV1 is exceptionally efficient at compressing text and static lines without blocky DCT artifacts.
   - LiveKit client supports setting `backupCodec: true` and specifying `videoCodec: 'av1'` with fallback to `vp9`/`h264` for browsers without AV1 support.
3. **H.264 Fallback**:
   - Universal hardware acceleration on low-end laptops and older mobile devices. Essential for preventing thermal throttling and high fan speeds.

---

## 4. Implementation Specification

### 4.1 Step 1: Quality Presets Definition (`plugins/love/src/types.ts`)

Extend `@hcengineering/love` types with standard video and screen sharing quality levels:

```typescript
export type CameraQualityPreset = 'low' | 'medium' | 'high' | 'ultra'
export type ScreenShareQualityPreset = '1080p15' | '1080p30' | '1440p30' | '4k15' | '4k30'
export type ScreenShareContentMode = 'detail' | 'motion'

export interface DevicesPreference extends Preference {
  micEnabled: boolean
  noiseCancellation: boolean
  blurRadius: number
  camEnabled: boolean
  // New quality preferences:
  cameraQuality?: CameraQualityPreset           // default: 'high' (1080p) or 'medium' (720p)
  screenShareQuality?: ScreenShareQualityPreset // default: '1080p30'
  screenShareContentMode?: ScreenShareContentMode // default: 'detail'
}
```

---

### 4.2 Step 2: Resolution & Encoding Presets Matrix (`plugins/love-resources/src/presets.ts`)

Create a dedicated preset mapping module in `plugins/love-resources`:

```typescript
import {
  VideoPreset,
  VideoPresets,
  ScreenSharePresets,
  type VideoCaptureOptions,
  type VideoEncoding,
  type ScreenShareCaptureOptions
} from 'livekit-client'
import type { CameraQualityPreset, ScreenShareQualityPreset, ScreenShareContentMode } from '@hcengineering/love'

export interface QualityProfile {
  capture: VideoCaptureOptions
  encoding: VideoEncoding
  simulcast: boolean
}

/**
 * Camera Quality Profiles
 */
export const CAMERA_PROFILES: Record<CameraQualityPreset, QualityProfile> = {
  low: {
    capture: {
      resolution: { width: 640, height: 360, frameRate: 24 }
    },
    encoding: {
      maxBitrate: 450_000,
      maxFramerate: 24
    },
    simulcast: false
  },
  medium: {
    // 720p (Current default)
    capture: {
      resolution: { width: 1280, height: 720, frameRate: 30 }
    },
    encoding: {
      maxBitrate: 1_700_000,
      maxFramerate: 30
    },
    simulcast: true
  },
  high: {
    // 1080p Full HD
    capture: {
      resolution: { width: 1920, height: 1080, frameRate: 30 }
    },
    encoding: {
      maxBitrate: 3_200_000,
      maxFramerate: 30
    },
    simulcast: true
  },
  ultra: {
    // 1440p / 4K Webcam
    capture: {
      resolution: { width: 2560, height: 1440, frameRate: 30 }
    },
    encoding: {
      maxBitrate: 5_500_000,
      maxFramerate: 30
    },
    simulcast: true
  }
}

/**
 * Screen Share Quality Profiles
 */
export const SCREEN_SHARE_PROFILES: Record<ScreenShareQualityPreset, {
  capture: ScreenShareCaptureOptions
  encoding: VideoEncoding
  simulcast: boolean
}> = {
  '1080p15': {
    capture: {
      resolution: ScreenSharePresets.h1080fps15.resolution
    },
    encoding: {
      maxBitrate: 2_500_000,
      maxFramerate: 15,
      priority: 'high'
    },
    simulcast: false
  },
  '1080p30': {
    capture: {
      resolution: ScreenSharePresets.h1080fps30.resolution
    },
    encoding: {
      maxBitrate: 4_500_000,
      maxFramerate: 30,
      priority: 'high'
    },
    simulcast: true
  },
  '1440p30': {
    capture: {
      resolution: { width: 2560, height: 1440, frameRate: 30 }
    },
    encoding: {
      maxBitrate: 7_000_000,
      maxFramerate: 30,
      priority: 'high'
    },
    simulcast: true
  },
  '4k15': {
    capture: {
      resolution: { width: 3840, height: 2160, frameRate: 15 }
    },
    encoding: {
      maxBitrate: 7_500_000,
      maxFramerate: 15,
      priority: 'high'
    },
    simulcast: true
  },
  '4k30': {
    capture: {
      resolution: { width: 3840, height: 2160, frameRate: 30 }
    },
    encoding: {
      maxBitrate: 10_000_000,
      maxFramerate: 30,
      priority: 'high'
    },
    simulcast: true
  }
}
```

---

### 4.3 Step 3: Refactoring `LiveKitClient` (`plugins/love-resources/src/liveKitClient.ts`)

Update `LiveKitClient` to dynamically apply quality profiles from preferences:

```typescript
import { CAMERA_PROFILES, SCREEN_SHARE_PROFILES } from './presets'
import { $myPreferences } from './stores'
import {
  VideoPresets,
  ScreenSharePresets,
  type VideoCaptureOptions,
  type VideoEncoding
} from 'livekit-client'

export class LiveKitClient {
  // ...
  constructor () {
    const camPreset = $myPreferences?.cameraQuality ?? 'high'
    const camProfile = CAMERA_PROFILES[camPreset]

    const screenPreset = $myPreferences?.screenShareQuality ?? '1080p30'
    const screenProfile = SCREEN_SHARE_PROFILES[screenPreset]

    const lkRoom = new LKRoom({
      adaptiveStream: true,
      dynacast: true,
      publishDefaults: {
        videoCodec: 'vp9',
        backupCodec: true, // Fallback to H.264 if VP9 is unsupported
        videoSimulcastLayers: [
          VideoPresets.h1080,
          VideoPresets.h540,
          VideoPresets.h270
        ],
        videoEncoding: camProfile.encoding,
        screenShareEncoding: screenProfile.encoding,
        screenShareSimulcastLayers: [
          ScreenSharePresets.h1080fps30,
          ScreenSharePresets.h540fps15
        ]
      },
      audioCaptureDefaults: {
        autoGainControl: true,
        echoCancellation: true,
        noiseSuppression: true
      },
      audioOutput: {
        deviceId: getSelectedSpeakerId()
      },
      videoCaptureDefaults: camProfile.capture
    })

    lkRoom.on(RoomEvent.Connected, this.onConnected)
    lkRoom.on(RoomEvent.Disconnected, this.onDisconnected)
    this.liveKitRoom = lkRoom
  }

  /**
   * Dynamically update camera resolution and re-acquire track if active
   */
  async setCameraQuality(preset: CameraQualityPreset): Promise<void> {
    const profile = CAMERA_PROFILES[preset]
    this.liveKitRoom.options.videoCaptureDefaults = profile.capture
    this.liveKitRoom.options.publishDefaults = {
      ...this.liveKitRoom.options.publishDefaults,
      videoEncoding: profile.encoding
    }

    const camPub = this.liveKitRoom.localParticipant.getTrackPublication(Track.Source.Camera)
    if (camPub && camPub.track && !camPub.isMuted) {
      // Re-acquire video track with new constraints
      await this.liveKitRoom.localParticipant.setCameraEnabled(false)
      await this.liveKitRoom.localParticipant.setCameraEnabled(true)
    }
  }

  /**
   * Start screen sharing with custom resolution and content hint
   */
  async setScreenShareEnabled(
    value: boolean,
    withAudio: boolean = false,
    qualityPreset: ScreenShareQualityPreset = '1080p30',
    contentMode: 'detail' | 'motion' = 'detail'
  ): Promise<void> {
    try {
      if (!value) {
        await this.liveKitRoom.localParticipant.setScreenShareEnabled(false)
        return
      }

      const profile = SCREEN_SHARE_PROFILES[qualityPreset]
      const captureOptions = {
        ...profile.capture,
        audio: withAudio,
        contentHint: contentMode === 'detail' ? 'text' : 'motion'
      }

      await this.liveKitRoom.localParticipant.setScreenShareEnabled(true, captureOptions)
    } catch (e) {
      console.error('Failed to set screen share with quality options:', e)
    }
  }
}
```

---

### 4.4 Step 4: UI Settings in `CamSettingPopup.svelte`

Add an intuitive quality picker to `plugins/love-resources/src/components/meeting/CamSettingPopup.svelte`:

```svelte
<script lang="ts">
  import { Component, Label, Loading, Progress, Toggle, Select } from '@hcengineering/ui'
  import love from '../../plugin'
  import { myPreferences } from '../../stores'
  import { blurProcessor, updateBlurRadius, liveKitClient } from '../../utils'
  import mediaPlugin, { getMediaDevices } from '@hcengineering/media'
  import type { CameraQualityPreset } from '@hcengineering/love'

  $: currentQuality = ($myPreferences?.cameraQuality ?? 'high') as CameraQualityPreset

  const qualityOptions: Array<{ value: CameraQualityPreset, label: string }> = [
    { value: 'ultra', label: 'Ultra (1440p)' },
    { value: 'high', label: 'High Definition (1080p)' },
    { value: 'medium', label: 'Standard (720p)' },
    { value: 'low', label: 'Data Saver (360p)' }
  ]

  async function handleQualityChange(e: CustomEvent<CameraQualityPreset>): Promise<void> {
    const selected = e.detail
    await liveKitClient.setCameraQuality(selected)
    // Update persisted preference
    // ... save to love.class.DevicesPreference ...
  }
</script>

<div class="antiPopup mediaPopup">
  <!-- Cam selector component -->
  {#await getMediaDevices(false, true)}
    <div class="p-4"><Loading /></div>
  {:then mediaInfo}
    <Component is={mediaPlugin.component.MediaPopupCamSelector} props={{ mediaInfo }} />
  {/await}

  <div class="grid p-3">
    <!-- Camera Quality Selector -->
    <Label label="Resolution" />
    <Select
      items={qualityOptions}
      value={currentQuality}
      on:change={handleQualityChange}
    />

    <!-- Background Blur -->
    {#if blurProcessor !== undefined}
      <Label label={love.string.Blur} />
      <Toggle
        showTooltip={{ label: love.string.BlurTooltip }}
        on={blurRadius >= 0.5}
        on:change={(e) => updateBlurRadius(e.detail ? 0.5 : 0)}
      />
      <!-- Blur slider -->
    {/if}
  </div>
</div>
```

---

### 4.5 Step 5: UI Settings in `ShareSettingPopup.svelte`

Add Resolution, Framerate, and Content Mode controls to `plugins/love-resources/src/components/ShareSettingPopup.svelte`:

```svelte
<script lang="ts">
  import { Label, Toggle, Select } from '@hcengineering/ui'
  import love from '../plugin'
  import { isShareWithSound, liveKitClient } from '../utils'
  import { myPreferences } from '../stores'
  import type { ScreenShareQualityPreset, ScreenShareContentMode } from '@hcengineering/love'

  let quality: ScreenShareQualityPreset = $myPreferences?.screenShareQuality ?? '1080p30'
  let contentMode: ScreenShareContentMode = $myPreferences?.screenShareContentMode ?? 'detail'

  const qualityOptions = [
    { value: '4k30', label: '4K Ultra HD (3840x2160, 30fps)' },
    { value: '1440p30', label: '2K Quad HD (2560x1440, 30fps)' },
    { value: '1080p30', label: 'Full HD 1080p (30fps - Recommended)' },
    { value: '1080p15', label: 'Full HD 1080p (15fps - Text Optimized)' }
  ]

  const modeOptions = [
    { value: 'detail', label: 'Crisp Text & Code (Detail)' },
    { value: 'motion', label: 'Fluid Animation (Motion)' }
  ]

  function updateSettings(): void {
    // Persist to user preferences
    // If currently sharing, re-apply track constraints
  }
</script>

<div class="antiPopup p-4 grid">
  <Label label={love.string.WithAudio} />
  <Toggle
    showTooltip={{ label: love.string.ShareWithAudioTooltip }}
    on={$isShareWithSound}
    on:change={(e) => {
      $isShareWithSound = e.detail
      updateSettings()
    }}
  />

  <Label label="Resolution" />
  <Select
    items={qualityOptions}
    value={quality}
    on:change={(e) => {
      quality = e.detail
      updateSettings()
    }}
  />

  <Label label="Optimization" />
  <Select
    items={modeOptions}
    value={contentMode}
    on:change={(e) => {
      contentMode = e.detail
      updateSettings()
    }}
  />
</div>
```

---

### 4.6 Step 6: Server-Side LiveKit Configuration (`livekit.yaml`)

For self-hosted or Dockerized LiveKit server instances, configure the SFU limit parameters and codecs to allow high-bitrate 1080p and 4K streams:

```yaml
port: 7880
bind_addresses:
  - ""
rtc:
  tcp_port: 7881
  port_range_start: 50000
  port_range_end: 60000
  use_external_ip: true

# Bandwidth Limits per participant
limit:
  # Max publisher bitrates (bits per second)
  # Allow up to 12 Mbps per client to support 4K screen sharing + 1080p camera
  max_publisher_bitrate: 15000000

room:
  auto_create: true
  empty_timeout: 300
  max_participants: 100
  codecs:
    # Prefer VP9 for SVC (scalable video coding)
    - mime: video/vp9
    # Support AV1 for ultra-efficient high-res screen sharing
    - mime: video/av1
    # Fallback to H.264
    - mime: video/h264
    - mime: video/vp8

# LiveKit Egress (Server-side recording & streaming)
egress:
  max_per_node: 6
  # Ensure egress nodes have CPU/GPU to encode 1080p/4K composite layouts
```

---

### 4.7 Step 7: Server Egress & Recording Presets (`services/love/src/preset.ts`)

Expand `services/love/src/preset.ts` to support 1080p60 and 4K recording presets:

```typescript
import { EncodingOptions, EncodingOptionsPreset } from 'livekit-server-sdk'

export interface RecordingPreset {
  name: string
  width: number
  height: number
  preset: EncodingOptions | EncodingOptionsPreset
}

export const RecordingPreset720p: RecordingPreset = {
  name: '720p',
  width: 1280,
  height: 720,
  preset: EncodingOptionsPreset.H264_720P_30
}

export const RecordingPreset1080p: RecordingPreset = {
  name: '1080p',
  width: 1920,
  height: 1080,
  preset: EncodingOptionsPreset.H264_1080P_30
}

export const RecordingPreset1080p60: RecordingPreset = {
  name: '1080p60',
  width: 1920,
  height: 1080,
  preset: EncodingOptionsPreset.H264_1080P_60
}

export const RecordingPreset4K: RecordingPreset = {
  name: '4k',
  width: 3840,
  height: 2160,
  preset: {
    width: 3840,
    height: 2160,
    depth: 24,
    framerate: 30,
    audioCodec: 1, // AAC
    audioBitrate: 192,
    audioFrequency: 48000,
    videoCodec: 1, // H264
    videoBitrate: 8000, // 8 Mbps
    keyFrameInterval: 4
  }
}

export function getRecordingPreset (name: string | undefined): RecordingPreset {
  switch (name?.toLowerCase()) {
    case '4k':
      return RecordingPreset4K
    case '1080p60':
      return RecordingPreset1080p60
    case '1080p':
      return RecordingPreset1080p
    case '720p':
    default:
      return RecordingPreset720p
  }
}
```

---

## 5. Performance, Bandwidth & CPU Impact Analysis

| Profile | Resolution | FPS | Bitrate (Target) | CPU Load (Encode) | Recommended For |
|---|---|---|---|---|---|
| **Data Saver** | 640x360 | 24 | ~400 kbps | Minimal (<5%) | Mobile data, weak cellular connections |
| **Standard (720p)** | 1280x720 | 30 | ~1.5 Mbps | Low (8-12%) | Default laptop webcam, multi-participant calls |
| **High Definition (1080p)** | 1920x1080 | 30 | ~3.2 Mbps | Moderate (15-20%) | Modern external webcams, executive meetings |
| **Screen Share 1080p30** | 1920x1080 | 30 | ~4.0 Mbps | Low (Hardware display capturer) | General software demos, IDE code sharing |
| **Screen Share 4K30** | 3840x2160 | 30 | ~8.0-10 Mbps | Moderate-High | Multi-window Retina presentations, high-DPI CAD/Design |

### Guardrails:
1. **Battery Awareness**: On battery power or when client detects thermal pressure (`navigator.hardwareConcurrency` low or WebRTC CPU overuse events), client can automatically downscale to `medium` (720p).
2. **Bandwidth Downgrade**: If WebRTC detects packet loss > 5% or round-trip-time (RTT) > 250ms, `adaptiveStream` seamlessly demotes subscriber feeds to lower spatial layers without interrupting audio.

---

## 6. Summary of Required File Changes

| File Path | Nature of Change | Purpose |
|---|---|---|
| `plugins/love/src/types.ts` | **Modify** | Add `CameraQualityPreset`, `ScreenShareQualityPreset`, and fields to `DevicesPreference`. |
| `plugins/love-resources/src/presets.ts` | **New** | Define `CAMERA_PROFILES` and `SCREEN_SHARE_PROFILES` with resolution, bitrates, and simulcast layers. |
| `plugins/love-resources/src/liveKitClient.ts` | **Modify** | Parameterize camera capture & encoding defaults; support dynamic quality switching via `setCameraQuality()` and `setScreenShareEnabled()`. |
| `plugins/love-resources/src/components/meeting/CamSettingPopup.svelte` | **Modify** | Add camera resolution selector (Data Saver, 720p, 1080p, 1440p). |
| `plugins/love-resources/src/components/ShareSettingPopup.svelte` | **Modify** | Add screen share resolution picker (1080p, 1440p, 4K) and Optimization mode (Detail vs Motion). |
| `desktop/src/ui/screenShare.ts` | **Modify** | Support 1440p and 4K screen capture options in Electron desktop capturer. |
| `services/love/src/preset.ts` | **Modify** | Add `RecordingPreset1080p60` and `RecordingPreset4K` for high-resolution egress/cloud recording. |
| `livekit.yaml` (Deployment) | **Configuration** | Increase `max_publisher_bitrate` to 15 Mbps; configure VP9/AV1/H.264 codec order. |

---

## 7. Verification and Validation Checklist

To manually verify the video resolution implementation:
1. **Camera 1080p Verification**:
   - Open meeting with a 1080p webcam. Select "High Definition (1080p)" in `CamSettingPopup`.
   - In Chrome, navigate to `chrome://webrtc-internals`. Inspect the local video track stats.
   - Verify `frameWidthInput: 1920`, `frameHeightInput: 1080`, `framesPerSecond: 30`, and bitrate ~3.2 Mbps.
2. **Simulcast & AdaptiveStream Verification**:
   - Subscriber joins on mobile or shrinks participant window to small tile.
   - Inspect subscriber `webrtc-internals`. Verify receiving lower layer (e.g. 540p or 270p).
   - Maximize participant video tile to full screen. Verify stream dynamically scales up to 1080p within 500ms.
3. **Screen Share 4K Verification**:
   - On a 4K display, select "4K Ultra HD (30fps)" in `ShareSettingPopup` and share full desktop.
   - Verify crisp rendering of small code fonts on subscriber screens without downscaling blur.
   - Verify framerate reaches 30fps during UI scrolling.
4. **Recording Preset Verification**:
   - Set `RECORDING_PRESET=1080p60` or `RECORDING_PRESET=4k` in `services/love`.
   - Start and stop recording in meeting room. Verify resulting MP4 in MinIO has expected resolution and framerate.
