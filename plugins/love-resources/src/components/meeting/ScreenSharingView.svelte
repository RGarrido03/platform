<script lang="ts">
  import { onMount } from 'svelte'
  import { translate } from '@hcengineering/platform'
  import { tooltip } from '@hcengineering/ui'
  import { Track } from 'livekit-client'

  import { liveKitClient, lk } from '../../utils'
  import { activeScreenShares, pinnedScreenShares } from '../../liveKitClient'
  import { layoutScreenShares } from '../../shareLayout'
  import { isScreenSharePipOpen, pipSupported, toggleScreenSharePip } from '../../pip'
  import love from '../../plugin'
  import IconPictureInPicture from '../icons/PictureInPicture.svelte'
  import ScreenShareTile from './ScreenShareTile.svelte'

  export let hasActiveTrack: boolean = false
  export let showLocalTrack: boolean = true

  $: allShares = Array.from($activeScreenShares.values())
  $: visibleShares = allShares.filter((s) => showLocalTrack || !s.isLocal)
  $: hasActiveTrack = visibleShares.length > 0
  $: ({ main, thumbs } = layoutScreenShares(visibleShares, $pinnedScreenShares))

  let pipLabel: string = ''

  $: void updatePipLabel()

  async function updatePipLabel (): Promise<void> {
    pipLabel = await translate(love.string.PictureInPicture)
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
  <div class="screens-wrapper">
    {#if pipSupported}
      <div class="screen-actions">
        <button
          class="screen-action"
          class:pressed={$isScreenSharePipOpen}
          aria-label={pipLabel}
          aria-pressed={$isScreenSharePipOpen}
          use:tooltip={{ label: love.string.PictureInPicture, direction: 'bottom' }}
          on:click={toggleScreenSharePip}
        >
          <IconPictureInPicture size={'small'} />
        </button>
      </div>
    {/if}

    <div
      class="screens-container"
      class:single={main.length === 1}
      class:dual={main.length === 2}
      class:multi={main.length > 2}
    >
      {#each main as share (share.id)}
        <ScreenShareTile {share} pinned={$pinnedScreenShares.has(share.id)} />
      {/each}
    </div>

    {#if thumbs.length > 0}
      <div class="screen-thumbs">
        {#each thumbs as share (share.id)}
          <ScreenShareTile {share} compact />
        {/each}
      </div>
    {/if}
  </div>
{/if}

<style lang="scss">
  .screens-wrapper {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    width: 100%;
    height: 100%;
    min-height: 0;
  }

  .screen-actions {
    position: absolute;
    top: 0.75rem;
    right: 0.75rem;
    z-index: 2;
    display: flex;
    gap: 0.5rem;
  }

  .screen-action {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0.35rem;
    border: none;
    border-radius: 0.375rem;
    background: rgba(0, 0, 0, 0.65);
    color: #f3f4f6;
    cursor: pointer;

    &:hover {
      background: rgba(0, 0, 0, 0.85);
    }

    &.pressed {
      background: #3b82f6;
      color: #ffffff;
    }
  }

  .screens-container {
    flex: 1 1 auto;
    min-height: 0;
    display: grid;
    width: 100%;
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

  .screen-thumbs {
    flex: 0 0 auto;
    display: flex;
    gap: 0.5rem;
    height: 5.5rem;
    padding-bottom: 0.25rem;
    overflow-x: auto;
    overflow-y: hidden;
  }
</style>
