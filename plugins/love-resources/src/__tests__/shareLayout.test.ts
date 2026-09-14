import { layoutScreenShares } from '../shareLayout'
import type { ScreenShareTrackInfo } from '../liveKitClient'

const share = (id: string): ScreenShareTrackInfo => ({ id } as ScreenShareTrackInfo)

const ids = (shares: ScreenShareTrackInfo[]): string[] => shares.map((share) => share.id)

describe('layoutScreenShares', () => {
  const a = share('a')
  const b = share('b')
  const c = share('c')

  it('gives every share the main area while nothing is pinned', () => {
    expect(layoutScreenShares([a, b, c], new Set())).toEqual({ main: [a, b, c], thumbs: [] })
  })

  it('keeps only the pinned shares in the main area and the others as thumbnails', () => {
    const { main, thumbs } = layoutScreenShares([a, b, c], new Set(['b']))

    expect(ids(main)).toEqual(['b'])
    expect(ids(thumbs)).toEqual(['a', 'c'])
  })

  it('keeps several pinned shares and preserves their order', () => {
    const { main, thumbs } = layoutScreenShares([a, b, c], new Set(['a', 'c']))

    expect(ids(main)).toEqual(['a', 'c'])
    expect(ids(thumbs)).toEqual(['b'])
  })

  it('ignores pins of shares that are gone', () => {
    expect(layoutScreenShares([a], new Set(['gone']))).toEqual({ main: [a], thumbs: [] })
  })

  it('handles an empty meeting', () => {
    expect(layoutScreenShares([], new Set(['a']))).toEqual({ main: [], thumbs: [] })
  })
})
