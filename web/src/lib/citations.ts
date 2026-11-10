// Citations in assistant answers.
//
// The agent cites a note inline as `[note:xxxxxxxx]`, the first 8 hex characters
// of the note id (see docs/API.md). The notes it retrieved arrive separately as
// the turn's `sources`. This module joins the two: each marker that matches a
// source becomes a numbered link, numbered by order of first appearance.

import type { Source } from '../api/types'

/** A marker, together with the space in front of it (if there is one). */
const MARKER = /( ?)\[note:([0-9a-f]{8})\]/g

/** A no-break space: keeps a citation number on the same line as the word it follows. */
const NBSP = ' '

/** The unfinished start of a marker at the very end of a text, such as `[note:3f2a`. */
const PARTIAL_MARKER = /\[(n(o(t(e(:[0-9a-f]{0,8})?)?)?)?)?$/

/** A citation link's href is `#cite-<number>`; the markdown renderer looks for it. */
const CITATION_HREF = /^#cite-(\d+)$/

export type Citation = {
  /** 1 for the first note cited in the answer, 2 for the next new one, and so on. */
  number: number
  /** null while the answer is still streaming and its sources have not arrived. */
  source: Source | null
}

export type LinkedText = {
  /**
   * The text with each resolved marker replaced by the markdown link
   * `[n](#cite-n)`. A space before the marker becomes a no-break space.
   */
  markdown: string
  /** The cited notes in order of first appearance. */
  citations: Citation[]
}

/**
 * Replaces citation markers with numbered markdown links.
 *
 * A marker that matches none of the sources is left as plain text. Pass
 * `sources: null` while the answer is streaming: the `sources` event only comes
 * after the last token, so until then every marker is numbered provisionally.
 */
export function linkCitations(text: string, sources: Source[] | null): LinkedText {
  const byPrefix = new Map<string, Citation>()

  const markdown = text.replace(MARKER, (match, space: string, prefix: string) => {
    let citation = byPrefix.get(prefix)
    if (!citation) {
      const source = sources?.find((candidate) => candidate.id.startsWith(prefix)) ?? null
      if (sources && !source) return match
      citation = { number: byPrefix.size + 1, source }
      byPrefix.set(prefix, citation)
    }
    return `${space && NBSP}[${citation.number}](#cite-${citation.number})`
  })

  return { markdown, citations: [...byPrefix.values()] }
}

/** The citation number of a link made by `linkCitations`, or null for any other link. */
export function citationNumber(href: string | undefined): number | null {
  const match = href?.match(CITATION_HREF)
  return match ? Number(match[1]) : null
}

/**
 * Hides a marker that has only partly arrived. Tokens can end in the middle of
 * a marker, and without this the raw `[note:3f` would flash on screen.
 */
export function stripPartialMarker(text: string): string {
  return text.replace(PARTIAL_MARKER, '')
}
