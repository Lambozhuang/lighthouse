import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { api, type InboxItem, type InboxStatus } from '../api'
import { keys } from '../api/keys'
import { Button, EmptyState, ErrorNote, fieldClass, Page, Spinner } from '../components/ui'
import { timeAgo } from '../lib/format'

const POLL_MS = 2000

const isInProgress = (item: InboxItem) => item.status === 'pending' || item.status === 'processing'

/** Drop text or a link, and watch the backend turn each item into a note. */
export function InboxPage() {
  const queryClient = useQueryClient()
  const inbox = useQuery({
    queryKey: keys.inbox,
    queryFn: api.listInbox,
    // Poll only while the backend is still working on something.
    refetchInterval: (query) => (query.state.data?.some(isInProgress) ? POLL_MS : false),
  })

  /** Puts an item returned by the API into the cached list right away. */
  function upsert(item: InboxItem) {
    queryClient.setQueryData<InboxItem[]>(keys.inbox, (items = []) =>
      items.some((existing) => existing.id === item.id)
        ? items.map((existing) => (existing.id === item.id ? item : existing))
        : [item, ...items],
    )
  }

  return (
    <Page title="Inbox">
      <DropForm onDropped={upsert} />

      <section aria-label="Inbox items">
        {inbox.isPending ? (
          <Spinner label="Loading inbox" />
        ) : inbox.isError ? (
          <ErrorNote message={inbox.error.message} onRetry={() => void inbox.refetch()} />
        ) : inbox.data.length === 0 ? (
          <EmptyState title="Nothing here yet">
            Whatever you add above shows up here while it is turned into a note.
          </EmptyState>
        ) : (
          <ul className="border-t border-line">
            {inbox.data.map((item) => (
              <InboxRow key={item.id} item={item} onRetried={upsert} />
            ))}
          </ul>
        )}
      </section>
    </Page>
  )
}

function DropForm({ onDropped }: { onDropped: (item: InboxItem) => void }) {
  const [content, setContent] = useState('')
  const drop = useMutation({
    mutationFn: api.drop,
    onSuccess: (item) => {
      setContent('')
      onDropped(item)
    },
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    if (content.trim() && !drop.isPending) drop.mutate(content.trim())
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-2">
      <label htmlFor="drop" className="text-sm font-medium">
        Add something
      </label>
      <textarea
        id="drop"
        rows={4}
        maxLength={200_000}
        placeholder="Paste text or a link"
        value={content}
        onChange={(event) => setContent(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) submit(event)
        }}
        className={`${fieldClass} resize-y`}
      />
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <p className="text-sm text-muted">
          A link on its own is fetched and summarized. Anything else is filed as text.
        </p>
        <Button type="submit" variant="primary" disabled={!content.trim() || drop.isPending}>
          {drop.isPending ? 'Adding…' : 'Add to inbox'}
        </Button>
      </div>
      {drop.isError && <ErrorNote message={drop.error.message} />}
    </form>
  )
}

function InboxRow({ item, onRetried }: { item: InboxItem; onRetried: (item: InboxItem) => void }) {
  const retry = useMutation({ mutationFn: api.retryInboxItem, onSuccess: onRetried })

  return (
    <li className="flex flex-col gap-1.5 border-b border-line py-3.5">
      <div className="flex items-start justify-between gap-4">
        <p className="line-clamp-2 min-w-0 wrap-anywhere">{item.content}</p>
        <StatusBadge status={item.status} />
      </div>

      {item.status === 'failed' && (
        <p className="text-sm text-danger">{item.error ?? 'Something went wrong.'}</p>
      )}
      {retry.isError && (
        <p role="alert" className="text-sm text-danger">
          {retry.error.message}
        </p>
      )}

      <div className="flex min-h-6 flex-wrap items-center gap-x-3 text-sm text-muted">
        <span>{item.kind === 'url' ? 'Link' : 'Text'}</span>
        <time dateTime={item.created_at}>{timeAgo(item.created_at)}</time>
        {item.status === 'done' && item.note_id && (
          <Link to={`/notes/${item.note_id}`} className="font-medium text-accent underline-offset-2 hover:underline">
            View note
          </Link>
        )}
        {item.status === 'failed' && (
          <button
            className="font-medium text-accent underline-offset-2 hover:underline disabled:opacity-50"
            disabled={retry.isPending}
            onClick={() => retry.mutate(item.id)}
          >
            {retry.isPending ? 'Retrying…' : 'Retry'}
          </button>
        )}
      </div>
    </li>
  )
}

const statusLooks: Record<InboxStatus, { label: string; dot: string }> = {
  pending: { label: 'Pending', dot: 'bg-muted' },
  processing: { label: 'Processing', dot: 'bg-warn' },
  done: { label: 'Done', dot: 'bg-ok' },
  failed: { label: 'Failed', dot: 'bg-danger' },
}

function StatusBadge({ status }: { status: InboxStatus }) {
  const { label, dot } = statusLooks[status]
  return (
    <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-line px-2.5 py-0.5 text-xs font-medium">
      <span className={`size-1.5 rounded-full ${dot}`} />
      {label}
    </span>
  )
}
