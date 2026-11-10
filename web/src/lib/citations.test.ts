import { describe, expect, it } from 'vitest'
import type { Source } from '../api/types'
import { citationNumber, linkCitations, stripPartialMarker } from './citations'

const alpha: Source = {
  id: 'aaaaaaaa-1111-4111-8111-111111111111',
  title: 'Alpha',
  source_url: 'https://example.com/alpha',
}
const beta: Source = { id: 'bbbbbbbb-2222-4222-8222-222222222222', title: 'Beta', source_url: null }
const gamma: Source = { id: 'cccccccc-3333-4333-8333-333333333333', title: 'Gamma', source_url: null }

describe('linkCitations', () => {
  it('replaces a marker with a numbered link', () => {
    const result = linkCitations('Water boils at 100 C.[note:aaaaaaaa]', [alpha])
    expect(result.markdown).toBe('Water boils at 100 C.[1](#cite-1)')
    expect(result.citations).toEqual([{ number: 1, source: alpha }])
  })

  it('numbers notes by first appearance, not by their order in sources', () => {
    const text = 'One[note:bbbbbbbb], two[note:cccccccc], three[note:aaaaaaaa].'
    const result = linkCitations(text, [alpha, beta, gamma])
    expect(result.markdown).toBe('One[1](#cite-1), two[2](#cite-2), three[3](#cite-3).')
    expect(result.citations.map((citation) => citation.source)).toEqual([beta, gamma, alpha])
  })

  it('reuses the number when a note is cited again', () => {
    const text = 'a[note:aaaaaaaa] b[note:bbbbbbbb] c[note:aaaaaaaa]'
    const result = linkCitations(text, [alpha, beta])
    expect(result.markdown).toBe('a[1](#cite-1) b[2](#cite-2) c[1](#cite-1)')
    expect(result.citations).toHaveLength(2)
  })

  it('leaves unknown markers as plain text and does not give them a number', () => {
    const text = 'Known[note:bbbbbbbb], unknown [note:deadbeef], known[note:aaaaaaaa].'
    const result = linkCitations(text, [alpha, beta])
    expect(result.markdown).toBe('Known[1](#cite-1), unknown [note:deadbeef], known[2](#cite-2).')
    expect(result.citations.map((citation) => citation.number)).toEqual([1, 2])
  })

  it('ignores text that only looks like a marker', () => {
    const text = '[note:AAAAAAAA] [note:aaaa] [note:aaaaaaaaa] [notes:aaaaaaaa] note:aaaaaaaa'
    expect(linkCitations(text, [alpha])).toEqual({ markdown: text, citations: [] })
  })

  it('handles markers next to each other', () => {
    const result = linkCitations('Both agree[note:aaaaaaaa][note:bbbbbbbb].', [alpha, beta])
    expect(result.markdown).toBe('Both agree[1](#cite-1)[2](#cite-2).')
  })

  it('turns the space before a marker into a no-break space', () => {
    const result = linkCitations('It floats [note:aaaaaaaa] and sinks [note:deadbeef].', [alpha])
    expect(result.markdown).toBe('It floats [1](#cite-1) and sinks [note:deadbeef].')
  })

  it('returns no citations for sources that the text never cites', () => {
    expect(linkCitations('No markers here.', [alpha, beta]).citations).toEqual([])
  })

  it('numbers every marker provisionally while the sources are not known yet', () => {
    const result = linkCitations('First[note:bbbbbbbb], second[note:deadbeef].', null)
    expect(result.markdown).toBe('First[1](#cite-1), second[2](#cite-2).')
    expect(result.citations).toEqual([
      { number: 1, source: null },
      { number: 2, source: null },
    ])
  })

  it('gives the same result on repeated calls', () => {
    const text = 'a[note:aaaaaaaa] and b[note:bbbbbbbb]'
    expect(linkCitations(text, [alpha, beta])).toEqual(linkCitations(text, [alpha, beta]))
  })
})

describe('citationNumber', () => {
  it('reads the number from a citation link', () => {
    expect(citationNumber('#cite-1')).toBe(1)
    expect(citationNumber('#cite-12')).toBe(12)
  })

  it('returns null for other links', () => {
    expect(citationNumber('https://example.com/#cite-1')).toBeNull()
    expect(citationNumber('#cite-')).toBeNull()
    expect(citationNumber('#section')).toBeNull()
    expect(citationNumber(undefined)).toBeNull()
  })
})

describe('stripPartialMarker', () => {
  it('removes an unfinished marker at the end', () => {
    for (const tail of ['[', '[n', '[note', '[note:', '[note:3f2a', '[note:3f2a9c1e']) {
      expect(stripPartialMarker(`As noted ${tail}`), tail).toBe('As noted ')
    }
  })

  it('keeps complete markers and ordinary text', () => {
    for (const text of ['Done [note:3f2a9c1e]', 'See [note:3f2a9c1e] for more', 'a [link', 'x[0]']) {
      expect(stripPartialMarker(text), text).toBe(text)
    }
  })
})
