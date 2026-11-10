import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { api, ApiError } from '../api'
import { keys } from '../api/keys'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { ArrowLeftIcon, TrashIcon } from '../components/icons'
import { Button, ErrorNote, SourceLink, Spinner, TagLink } from '../components/ui'
import { formatDate } from '../lib/format'

/** One note in full. */
export function NotePage() {
  const noteId = useParams().noteId!
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const note = useQuery({ queryKey: keys.note(noteId), queryFn: () => api.getNote(noteId) })

  const remove = useMutation({
    mutationFn: () => api.deleteNote(noteId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: keys.notes() })
      await navigate('/notes', { replace: true })
    },
  })

  return (
    <div className="h-full overflow-y-auto">
      <article className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-6 sm:px-6 md:py-10">
        <Link to="/notes" className="inline-flex items-center gap-1.5 self-start text-sm text-muted hover:text-ink">
          <ArrowLeftIcon size={16} />
          Notes
        </Link>

        {note.isPending ? (
          <Spinner label="Loading note" />
        ) : note.isError ? (
          note.error instanceof ApiError && note.error.status === 404 ? (
            <p className="text-muted">This note does not exist. It may have been deleted.</p>
          ) : (
            <ErrorNote message={note.error.message} onRetry={() => void note.refetch()} />
          )
        ) : (
          <>
            <header className="flex flex-col gap-3">
              <h1 className="text-2xl font-semibold tracking-tight text-balance">{note.data.title}</h1>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
                <time dateTime={note.data.created_at}>{formatDate(note.data.created_at)}</time>
                <SourceLink url={note.data.source_url} title={note.data.source_title} />
              </div>
              {note.data.tags.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {note.data.tags.map((tag) => (
                    <TagLink key={tag} tag={tag} />
                  ))}
                </div>
              )}
            </header>

            <Section title="Summary">
              <p>{note.data.summary}</p>
            </Section>

            {note.data.key_points.length > 0 && (
              <Section title="Key points">
                <ul className="flex list-disc flex-col gap-1.5 pl-5 marker:text-muted">
                  {note.data.key_points.map((point, index) => (
                    <li key={index}>{point}</li>
                  ))}
                </ul>
              </Section>
            )}

            <Section title="Full text">
              {/* The body is untrusted web content: shown as plain text, never as HTML or markdown. */}
              <p className="wrap-anywhere whitespace-pre-wrap">{note.data.body}</p>
            </Section>

            <footer className="border-t border-line pt-5">
              <Button
                onClick={() => {
                  remove.reset()
                  setConfirming(true)
                }}
              >
                <TrashIcon size={16} />
                Delete note
              </Button>
            </footer>

            {confirming && (
              <ConfirmDialog
                title="Delete this note?"
                confirmLabel="Delete"
                busy={remove.isPending}
                error={remove.error?.message}
                onConfirm={() => remove.mutate()}
                onCancel={() => setConfirming(false)}
              >
                “{note.data.title}” will be removed from your library. This cannot be undone.
              </ConfirmDialog>
            )}
          </>
        )}
      </article>
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex max-w-[70ch] flex-col gap-2 leading-relaxed">
      <h2 className="text-xs font-semibold tracking-wider text-muted uppercase">{title}</h2>
      {children}
    </section>
  )
}
