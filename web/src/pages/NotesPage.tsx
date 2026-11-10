import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { api, type NoteSummary } from '../api'
import { keys } from '../api/keys'
import { SearchIcon } from '../components/icons'
import { Button, EmptyState, ErrorNote, fieldClass, Page, SourceLink, Spinner, TagLink } from '../components/ui'
import { formatDate } from '../lib/format'

const PAGE_SIZE = 50
const SEARCH_DELAY_MS = 300

/**
 * The notes library. The search text and the tag filter live in the URL
 * (`/notes?q=...&tag=...`), so they survive a reload and the back button.
 */
export function NotesPage() {
  const [params, setParams] = useSearchParams()
  const q = params.get('q') ?? ''
  const tag = params.get('tag') ?? ''

  // The input updates at once; the URL (and so the query) follows after a pause in typing.
  const [search, setSearch] = useState(q)
  useEffect(() => {
    if (search.trim() === q) return
    const timer = setTimeout(() => {
      setParams(
        (previous) => {
          const next = new URLSearchParams(previous)
          if (search.trim()) next.set('q', search.trim())
          else next.delete('q')
          return next
        },
        { replace: true },
      )
    }, SEARCH_DELAY_MS)
    return () => clearTimeout(timer)
  }, [search, q, setParams])

  const filters = { q, tag }
  const notes = useInfiniteQuery({
    queryKey: keys.notes(filters),
    queryFn: ({ pageParam }) => api.listNotes({ ...filters, limit: PAGE_SIZE, offset: pageParam }),
    initialPageParam: 0,
    // A full page means there may be more.
    getNextPageParam: (lastPage, pages) =>
      lastPage.length === PAGE_SIZE ? pages.length * PAGE_SIZE : undefined,
  })
  const list = notes.data?.pages.flat()
  const tags = useKnownTags(tag)

  return (
    <Page title="Notes">
      <div className="flex flex-col gap-3">
        <div className="relative">
          <label htmlFor="search" className="sr-only">
            Search notes
          </label>
          <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-muted">
            <SearchIcon size={18} />
          </span>
          <input
            id="search"
            type="search"
            placeholder="Search notes"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            className={`${fieldClass} pl-10`}
          />
        </div>
        {tags.length > 0 && (
          <nav aria-label="Filter by tag" className="flex flex-wrap gap-1.5">
            {tags.map((name) => (
              <TagLink key={name} tag={name} active={name === tag} />
            ))}
          </nav>
        )}
      </div>

      {notes.isPending ? (
        <Spinner label="Loading notes" />
      ) : notes.isError ? (
        <ErrorNote message={notes.error.message} onRetry={() => void notes.refetch()} />
      ) : list?.length === 0 ? (
        q || tag ? (
          <EmptyState title="No notes match">Try another word, or clear the tag filter.</EmptyState>
        ) : (
          <EmptyState title="No notes yet">
            Add a link or some text in the inbox and it will be filed here as a note.
          </EmptyState>
        )
      ) : (
        <>
          <ul className="border-t border-line">
            {list?.map((note) => (
              <NoteRow key={note.id} note={note} />
            ))}
          </ul>
          {notes.hasNextPage && (
            <Button className="self-start" disabled={notes.isFetchingNextPage} onClick={() => void notes.fetchNextPage()}>
              {notes.isFetchingNextPage ? 'Loading…' : 'Show more'}
            </Button>
          )}
        </>
      )}
    </Page>
  )
}

function NoteRow({ note }: { note: NoteSummary }) {
  return (
    // The title link is stretched over the whole row (after:inset-0); tags and
    // the source link sit above it (relative z-10) so they stay clickable.
    <li className="relative flex flex-col gap-1.5 border-b border-line py-4">
      <h2 className="font-medium">
        <Link to={`/notes/${note.id}`} className="underline-offset-2 after:absolute after:inset-0 hover:underline">
          {note.title}
        </Link>
      </h2>
      <p className="line-clamp-2 text-muted">{note.summary}</p>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 pt-0.5 text-sm text-muted">
        <time dateTime={note.created_at}>{formatDate(note.created_at)}</time>
        <span className="relative z-10 inline-flex min-w-0 empty:hidden">
          <SourceLink url={note.source_url} />
        </span>
        <span className="relative z-10 flex flex-wrap gap-1.5">
          {note.tags.map((tag) => (
            <TagLink key={tag} tag={tag} />
          ))}
        </span>
      </div>
    </li>
  )
}

/**
 * The tags to offer as filters. The API has no endpoint that lists all tags,
 * so these are the tags of the most recent notes, most used first.
 */
function useKnownTags(selected: string): string[] {
  const recent = useQuery({
    queryKey: keys.notes({ limit: PAGE_SIZE }),
    queryFn: () => api.listNotes({ limit: PAGE_SIZE }),
  })
  const counts = new Map<string, number>()
  for (const note of recent.data ?? []) {
    for (const tag of note.tags) counts.set(tag, (counts.get(tag) ?? 0) + 1)
  }
  const tags = [...counts.keys()].sort((a, b) => counts.get(b)! - counts.get(a)! || a.localeCompare(b))
  // A tag from the URL is always shown, so that it can be switched off.
  return selected && !counts.has(selected) ? [selected, ...tags] : tags
}
