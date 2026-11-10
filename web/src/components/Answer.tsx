import { createContext, useContext, useMemo, type ComponentProps } from 'react'
import Markdown from 'react-markdown'
import { Link } from 'react-router'
import type { Source } from '../api/types'
import {
  citationNumber,
  linkCitations,
  stripPartialMarker,
  type Citation,
} from '../lib/citations'
import { SourceLink } from './ui'

type Props = {
  text: string
  /** The notes retrieved for this answer; null while they are not known yet. */
  sources: Source[] | null
  /** The text is still arriving. */
  streaming?: boolean
}

const chipShape =
  'mx-0.5 inline-flex h-[1.35em] min-w-[1.35em] items-center justify-center rounded px-1 align-[0.08em] text-[0.75em] font-semibold no-underline tabular-nums'
const chipClass = `${chipShape} bg-accent-soft text-accent`

/** An assistant answer: markdown with citation chips, and the list of sources below it. */
export function Answer({ text, sources, streaming = false }: Props) {
  const { markdown, citations } = useMemo(
    () => linkCitations(streaming ? stripPartialMarker(text) : text, sources),
    [text, sources, streaming],
  )
  const cited = citations.filter((citation) => citation.source !== null)
  const uncited = (sources ?? []).filter((source) => cited.every((citation) => citation.source?.id !== source.id))

  return (
    <>
      <div className="markdown">
        <CitationsContext value={citations}>
          {/* No images: an answer is model output, and an image URL would be fetched without a click. */}
          <Markdown components={{ a: MarkdownLink }} disallowedElements={['img']}>
            {markdown}
          </Markdown>
        </CitationsContext>
      </div>

      {cited.length + uncited.length > 0 && (
        <section aria-label="Sources" className="border-t border-line pt-3 text-sm">
          <h3 className="text-xs font-semibold tracking-wider text-muted uppercase">Sources</h3>
          <ol className="mt-2 flex flex-col gap-1.5">
            {cited.map(({ number, source }) => (
              <SourceItem key={number} source={source!} marker={number} />
            ))}
            {uncited.map((source) => (
              <SourceItem key={source.id} source={source} />
            ))}
          </ol>
        </section>
      )}
    </>
  )
}

/** One line of the sources list. Notes that were read but not cited have no number. */
function SourceItem({ source, marker }: { source: Source; marker?: number }) {
  return (
    <li className="flex items-baseline gap-2">
      <span className={marker ? chipClass : `${chipShape} text-muted`}>
        {marker ?? '–'}
      </span>
      <span className="flex min-w-0 flex-wrap items-baseline gap-x-3">
        <Link to={`/notes/${source.id}`} className="underline-offset-2 hover:underline">
          {source.title}
        </Link>
        <SourceLink url={source.source_url} />
      </span>
    </li>
  )
}

// react-markdown calls MarkdownLink for every link. Citation links carry only
// their number (`#cite-2`), so the component reads the rest from this context.
const CitationsContext = createContext<Citation[]>([])

function MarkdownLink({ href, children }: ComponentProps<'a'>) {
  const citations = useContext(CitationsContext)
  const number = citationNumber(href)
  if (number === null) {
    return (
      <a href={href} target="_blank" rel="noreferrer">
        {children}
      </a>
    )
  }

  const source = citations.find((citation) => citation.number === number)?.source
  // Sources arrive after the text: until then the chip is not a link yet.
  if (!source) return <span className={chipClass}>{number}</span>
  return (
    <Link
      to={`/notes/${source.id}`}
      title={source.title}
      aria-label={`Source ${number}: ${source.title}`}
      className={`${chipClass} hover:bg-accent hover:text-on-accent`}
    >
      {number}
    </Link>
  )
}
