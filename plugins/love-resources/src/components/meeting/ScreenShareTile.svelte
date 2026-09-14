<!--
// Copyright © 2025 Hardcore Engineering Inc.
//
// Licensed under the Eclipse Public License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License. You may
// obtain a copy of the License at https://www.eclipse.org/legal/epl-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
//
// See the License for the specific language governing permissions and
// limitations under the License.
-->
<script lang="ts">
  import { translate } from '@hcengineering/platform'
  import { tooltip } from '@hcengineering/ui'
  import { Track } from 'livekit-client'

  import { toggleScreenSharePin, type ScreenShareTrackInfo } from '../../liveKitClient'
  import love from '../../plugin'
  import IconPin from '../icons/Pin.svelte'

  export let share: ScreenShareTrackInfo
  export let pinned: boolean = false
  export let compact: boolean = false

  let pinLabel: string = ''

  $: void updatePinLabel(pinned)

  async function updatePinLabel (isPinned: boolean): Promise<void> {
    pinLabel = await translate(isPinned ? love.string.Unpin : love.string.Pin)
  }

  function attachTrack (node: HTMLVideoElement, track: Track) {
    track.attach(node)
    return {
      update (newTrack: Track) {
        if (newTrack !== track) {
          track.detach(node)
          track = newTrack
          track.attach(node)
        }
      },
      destroy () {
        track.detach(node)
      }
    }
  }
</script>

<div class="screen-tile" class:compact class:pinned>
  <!-- svelte-ignore a11y-media-has-caption -->
  <video class="screen" use:attachTrack={share.track} autoplay playsinline muted={share.isLocal}></video>
  <div class="screen-badge">
    <span class="presenter-name">{share.participant?.name || 'Screen'}</span>
    {#if share.isLocal}
      <span class="local-tag">You</span>
    {/if}
  </div>
  <button
    class="pin-button"
    class:active={pinned}
    aria-label={pinLabel}
    aria-pressed={pinned}
    use:tooltip={{ label: pinned ? love.string.Unpin : love.string.Pin, direction: 'bottom' }}
    on:click={() => toggleScreenSharePin(share.id)}
  >
    <IconPin size={'small'} />
  </button>
</div>

<style lang="scss">
  .screen-tile {
    position: relative;
    width: 100%;
    height: 100%;
    min-width: 0;
    min-height: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #0b0d11;
    border-radius: 0.75rem;
    overflow: hidden;

    &.pinned {
      outline: 2px solid #3b82f6;
      outline-offset: -2px;
    }

    &.compact {
      flex: 0 0 auto;
      width: auto;
      height: 100%;
      aspect-ratio: 16 / 9;
      border-radius: 0.5rem;
    }

    .screen {
      object-fit: contain;
      max-width: 100%;
      max-height: 100%;
      height: 100%;
      width: 100%;
      border-radius: inherit;
    }

    .screen-badge {
      position: absolute;
      bottom: 0.75rem;
      left: 0.75rem;
      display: flex;
      align-items: center;
      gap: 0.4rem;
      padding: 0.25rem 0.6rem;
      background: rgba(0, 0, 0, 0.65);
      border-radius: 0.375rem;
      backdrop-filter: blur(8px);
      pointer-events: none;
      max-width: calc(100% - 1.5rem);

      .presenter-name {
        color: #f3f4f6;
        font-size: 0.8rem;
        font-weight: 500;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .local-tag {
        background: #3b82f6;
        color: #ffffff;
        font-size: 0.7rem;
        font-weight: 600;
        padding: 0.05rem 0.35rem;
        border-radius: 0.25rem;
      }
    }

    .pin-button {
      position: absolute;
      top: 0.5rem;
      right: 0.5rem;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 0.25rem;
      border: none;
      border-radius: 0.375rem;
      background: rgba(0, 0, 0, 0.65);
      color: #f3f4f6;
      cursor: pointer;
      opacity: 0;
      transition: opacity 0.15s ease-in-out;

      &.active {
        background: #3b82f6;
        color: #ffffff;
        opacity: 1;
      }
    }

    &:hover .pin-button,
    &:focus-within .pin-button,
    &.compact .pin-button {
      opacity: 1;
    }

    &.compact {
      .screen-badge {
        bottom: 0.35rem;
        left: 0.35rem;
        padding: 0.1rem 0.35rem;

        .presenter-name {
          font-size: 0.65rem;
        }
      }

      .pin-button {
        top: 0.35rem;
        right: 0.35rem;
      }
    }
  }
</style>
