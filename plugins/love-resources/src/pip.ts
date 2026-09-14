import { derived, writable } from 'svelte/store'
import type { Track } from 'livekit-client'

import { activeScreenShares, pinnedScreenShares, type ScreenShareTrackInfo } from './liveKitClient'
import { layoutScreenShares } from './shareLayout'

// Document Picture-in-Picture hosts arbitrary markup, which is what makes a window with several
// screen shares possible: the plain video PiP only ever fits one element.
interface DocumentPictureInPictureApi {
  requestWindow: (options?: { width?: number, height?: number }) => Promise<Window>
  window: Window | null
}

function pipApi (): DocumentPictureInPictureApi | undefined {
  if (typeof window === 'undefined') return undefined
  return (window as unknown as { documentPictureInPicture?: DocumentPictureInPictureApi })
    .documentPictureInPicture
}

export const pipSupported: boolean = pipApi() !== undefined

export const isScreenSharePipOpen = writable<boolean>(false)

// The window shows the same selection as the main area: every share while nothing is pinned,
// only the pinned ones afterwards.
const pipShares = derived([activeScreenShares, pinnedScreenShares], ([$shares, $pinned]) =>
  layoutScreenShares(Array.from($shares.values()), $pinned).main
)

interface PipTile {
  root: HTMLDivElement
  video: HTMLVideoElement
  name: HTMLSpanElement
  track: Track
}

const PIP_STYLE = `
  body { margin: 0; background: #0b0d11; }
  .screens { display: grid; gap: 0.25rem; width: 100vw; height: 100vh; padding: 0.25rem; box-sizing: border-box; }
  .tile { position: relative; display: flex; align-items: center; justify-content: center; min-width: 0; min-height: 0; background: #000000; border-radius: 0.25rem; overflow: hidden; }
  .tile video { width: 100%; height: 100%; object-fit: contain; }
  .name { position: absolute; left: 0.25rem; bottom: 0.25rem; max-width: calc(100% - 0.5rem); padding: 0 0.25rem; border-radius: 0.125rem; background: rgba(0, 0, 0, 0.65); color: #f3f4f6; font: 500 11px/1.5 system-ui, sans-serif; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
`

class ScreenSharePip {
  private win: Window | undefined
  private root: HTMLDivElement | undefined
  private tiles = new Map<string, PipTile>()
  private unsubscribe: (() => void) | undefined

  async open (): Promise<void> {
    if (this.win !== undefined) return
    const api = pipApi()
    if (api === undefined) return

    const win = await api.requestWindow({ width: 480, height: 300 })
    this.win = win

    const style = win.document.createElement('style')
    style.textContent = PIP_STYLE
    win.document.head.append(style)

    this.root = win.document.createElement('div')
    this.root.className = 'screens'
    win.document.body.append(this.root)

    // Fires both when the user closes the window and when we close it ourselves.
    win.addEventListener('pagehide', () => {
      this.dispose()
    })
    this.unsubscribe = pipShares.subscribe((shares) => {
      this.sync(shares)
    })
    isScreenSharePipOpen.set(true)
  }

  close (): void {
    this.win?.close()
  }

  toggle (): void {
    if (this.win !== undefined) {
      this.close()
    } else {
      void this.open()
    }
  }

  private sync (shares: ScreenShareTrackInfo[]): void {
    const doc = this.win?.document
    const root = this.root
    if (doc === undefined || root === undefined) return

    // Nothing left to watch, including the meeting being over: do not leave an empty window.
    if (shares.length === 0) {
      this.close()
      return
    }

    const alive = new Set(shares.map((share) => share.id))
    for (const [id, tile] of Array.from(this.tiles.entries())) {
      if (!alive.has(id)) {
        tile.track.detach(tile.video)
        tile.root.remove()
        this.tiles.delete(id)
      }
    }

    for (const share of shares) {
      let tile = this.tiles.get(share.id)
      if (tile === undefined) {
        tile = this.createTile(doc, share)
        this.tiles.set(share.id, tile)
      } else if (tile.track !== share.track) {
        tile.track.detach(tile.video)
        share.track.attach(tile.video)
        tile.track = share.track
      }
      tile.video.muted = share.isLocal
      tile.name.textContent = share.participant?.name ?? ''
      // Re-appending keeps the window order in step with the main area.
      root.append(tile.root)
    }

    root.style.gridTemplateColumns = `repeat(${shares.length > 1 ? 2 : 1}, minmax(0, 1fr))`
  }

  private createTile (doc: Document, share: ScreenShareTrackInfo): PipTile {
    const root = doc.createElement('div')
    root.className = 'tile'

    const video = doc.createElement('video')
    video.autoplay = true
    video.playsInline = true
    video.muted = share.isLocal
    share.track.attach(video)
    // A freshly created document needs an explicit nudge; a blocked play is not fatal.
    void video.play().catch((err) => {
      console.log('Failed to play screen share in picture in picture', err)
    })

    const name = doc.createElement('span')
    name.className = 'name'

    root.append(video, name)
    return { root, video, name, track: share.track }
  }

  private dispose (): void {
    this.unsubscribe?.()
    this.unsubscribe = undefined
    for (const tile of this.tiles.values()) {
      tile.track.detach(tile.video)
    }
    this.tiles.clear()
    this.root = undefined
    this.win = undefined
    isScreenSharePipOpen.set(false)
  }
}

const pip = new ScreenSharePip()

export function toggleScreenSharePip (): void {
  pip.toggle()
}
