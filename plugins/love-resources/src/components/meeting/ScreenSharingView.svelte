<script lang="ts">
  import { onMount } from 'svelte'
  import { liveKitClient, lk } from '../../utils'
  import { activeScreenShares, type ScreenShareTrackInfo } from '../../liveKitClient'
  import { Track } from 'livekit-client'

  export let hasActiveTrack: boolean = false
  export let showLocalTrack: boolean = true

  $: allShares = Array.from($activeScreenShares.values())
  $: visibleShares = allShares.filter((s) => showLocalTrack || !s.isLocal)
  $: hasActiveTrack = visibleShares.length > 0

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

  onMount(async () => {
    await liveKitClient.awaitConnect()

    for (const participant of lk.remoteParticipants.values()) {
      for (const publication of participant.trackPublications.values()) {
        if (publication.track?.kind === Track.Kind.Video && publication.track.source === Track.Source.ScreenShare) {
          const id = publication.trackSid || publication.track.sid || `${participant.identity}-${Date.now()}`
          activeScreenShares.update((m) => {
            m.set(id, { id, track: publication.track!, publication, participant, isLocal: false })
            return new Map(m)
          })
        }
      }
    }

    if (showLocalTrack) {
      for (const publication of lk.localParticipant.trackPublications.values()) {
        if (publication.track?.kind === Track.Kind.Video && publication.track.source === Track.Source.ScreenShare) {
          const id = publication.trackSid || publication.track.sid || `${lk.localParticipant.identity}-local`
          activeScreenShares.update((m) => {
            m.set(id, { id, track: publication.track!, publication, participant: lk.localParticipant, isLocal: true })
            return new Map(m)
          })
        }
      }
    }
  })
</script>

{#if visibleShares.length > 0}
  <div
    class="screens-container"
    class:single={visibleShares.length === 1}
    class:dual={visibleShares.length === 2}
    class:multi={visibleShares.length > 2}
  >
    {#each visibleShares as share (share.id)}
      <div class="screen-tile">
        <video
          class="screen"
          use:attachTrack={share.track}
          autoplay
          playsinline
          muted={share.isLocal}
        ></video>
        <div class="screen-badge">
          <span class="presenter-name">{share.participant?.name || 'Screen'}</span>
          {#if share.isLocal}
            <span class="local-tag">You</span>
          {/if}
        </div>
      </div>
    {/each}
  </div>
{/if}

<style lang="scss">
  .screens-container {
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

    &.dual {
      grid-template-columns: 1fr 1fr;
      grid-template-rows: 1fr;
    }

    &.multi {
      grid-template-columns: 1fr 1fr;
      grid-template-rows: 1fr 1fr;
    }
  }

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

    .screen {
      object-fit: contain;
      max-width: 100%;
      max-height: 100%;
      height: 100%;
      width: 100%;
      border-radius: 0.75rem;
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

      .presenter-name {
        color: #f3f4f6;
        font-size: 0.8rem;
        font-weight: 500;
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
  }
</style>
