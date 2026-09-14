import type { ScreenShareTrackInfo } from './liveKitClient'

export interface ScreenShareLayout {
  // Shares that get the main area: the pinned ones, or all of them while nothing is pinned.
  main: ScreenShareTrackInfo[]
  // The rest, shown as thumbnails under the main area while something is pinned.
  thumbs: ScreenShareTrackInfo[]
}

/**
 * Splits the active screen shares into the main area and the thumbnail strip. Shared by the
 * meeting view and the picture-in-picture window so both always show the same selection.
 */
export function layoutScreenShares (
  shares: ScreenShareTrackInfo[],
  pinned: ReadonlySet<string>
): ScreenShareLayout {
  const pinnedShares = shares.filter((share) => pinned.has(share.id))
  if (pinnedShares.length === 0) {
    return { main: shares, thumbs: [] }
  }
  return { main: pinnedShares, thumbs: shares.filter((share) => !pinned.has(share.id)) }
}
