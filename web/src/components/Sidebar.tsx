import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { NavLink, useMatch, useNavigate } from 'react-router'
import { api, type Thread } from '../api'
import { keys } from '../api/keys'
import { auth } from '../auth'
import { config } from '../config'
import { cx } from '../lib/format'
import { ConfirmDialog } from './ConfirmDialog'
import { CloseIcon, InboxIcon, LogoIcon, NotesIcon, PlusIcon, SignOutIcon, TrashIcon } from './icons'
import { IconButton } from './ui'

type Props = {
  email: string
  /** On narrow screens the sidebar is a drawer; this says whether it is showing. */
  open: boolean
  /** Called when a link is followed, so the drawer can close. */
  onNavigate: () => void
}

const rowClass = 'flex h-10 items-center gap-2.5 rounded-md px-3 text-sm transition-colors'

function rowState({ isActive }: { isActive: boolean }) {
  return cx(rowClass, isActive ? 'bg-hover font-medium' : 'text-muted hover:bg-hover hover:text-ink')
}

export function Sidebar({ email, open, onNavigate }: Props) {
  return (
    <aside
      className={cx(
        // A drawer below the md breakpoint, a fixed column from there on.
        'fixed inset-y-0 left-0 z-40 flex w-72 max-w-[85vw] flex-col border-r border-line bg-panel transition-[translate,visibility] duration-200 motion-reduce:transition-none md:static md:z-auto md:w-64 md:shrink-0',
        !open && 'max-md:invisible max-md:-translate-x-full',
      )}
    >
      <div className="flex h-14 shrink-0 items-center gap-2 pr-2 pl-4">
        <span className="text-accent">
          <LogoIcon size={22} />
        </span>
        <span className="font-semibold tracking-tight">Lighthouse</span>
        {config.mock && (
          <span className="rounded border border-line px-1.5 py-0.5 text-xs text-muted">mock data</span>
        )}
        <IconButton label="Close menu" onClick={onNavigate} className="ml-auto md:hidden">
          <CloseIcon />
        </IconButton>
      </div>

      <nav aria-label="Main" className="flex flex-col gap-0.5 px-2">
        <NavItem to="/chat" end icon={<PlusIcon />} onClick={onNavigate}>
          New chat
        </NavItem>
        <NavItem to="/inbox" icon={<InboxIcon />} onClick={onNavigate}>
          Inbox
        </NavItem>
        <NavItem to="/notes" icon={<NotesIcon />} onClick={onNavigate}>
          Notes
        </NavItem>
      </nav>

      <ThreadList onNavigate={onNavigate} />

      <div className="flex shrink-0 items-center gap-1 border-t border-line py-2 pr-2 pl-4">
        <span className="min-w-0 flex-1 truncate text-sm text-muted" title={email}>
          {email}
        </span>
        <IconButton label="Sign out" onClick={() => void auth.signOut()}>
          <SignOutIcon />
        </IconButton>
      </div>
    </aside>
  )
}

type NavItemProps = {
  to: string
  end?: boolean
  icon: ReactNode
  onClick: () => void
  children: ReactNode
}

function NavItem({ icon, children, ...props }: NavItemProps) {
  return (
    <NavLink className={rowState} {...props}>
      {icon}
      {children}
    </NavLink>
  )
}

function ThreadList({ onNavigate }: { onNavigate: () => void }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const openThreadId = useMatch('/chat/:threadId')?.params.threadId
  const threads = useQuery({ queryKey: keys.threads, queryFn: api.listThreads })
  const [deleting, setDeleting] = useState<Thread | null>(null)

  const remove = useMutation({
    mutationFn: (thread: Thread) => api.deleteThread(thread.id),
    onSuccess: (_, thread) => {
      setDeleting(null)
      queryClient.setQueryData<Thread[]>(keys.threads, (list) =>
        list?.filter((item) => item.id !== thread.id),
      )
      queryClient.removeQueries({ queryKey: keys.messages(thread.id) })
      if (thread.id === openThreadId) void navigate('/chat')
    },
  })

  return (
    <section aria-labelledby="chats-heading" className="mt-5 flex min-h-0 flex-1 flex-col">
      <h2 id="chats-heading" className="px-5 pb-1.5 text-xs font-semibold tracking-wider text-muted uppercase">
        Chats
      </h2>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {threads.isPending && <p className="px-3 py-2 text-sm text-muted">Loading…</p>}
        {threads.isError && (
          <p role="alert" className="px-3 py-2 text-sm text-muted">
            Could not load your chats.{' '}
            <button className="text-accent underline underline-offset-2" onClick={() => void threads.refetch()}>
              Try again
            </button>
          </p>
        )}
        {threads.data?.length === 0 && <p className="px-3 py-2 text-sm text-muted">No chats yet.</p>}

        <ul className="flex flex-col gap-0.5">
          {threads.data?.map((thread) => (
            <li key={thread.id} className="group relative">
              <NavLink to={`/chat/${thread.id}`} onClick={onNavigate} className={rowState} title={thread.title}>
                <span className="truncate pr-8">{thread.title}</span>
              </NavLink>
              {/* Shown on hover or keyboard focus; always shown on touch screens. */}
              <IconButton
                small
                label={`Delete chat: ${thread.title}`}
                onClick={() => {
                  remove.reset()
                  setDeleting(thread)
                }}
                className="absolute top-1 right-1 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 pointer-coarse:opacity-100"
              >
                <TrashIcon size={16} />
              </IconButton>
            </li>
          ))}
        </ul>
      </div>

      {deleting && (
        <ConfirmDialog
          title="Delete this chat?"
          confirmLabel="Delete"
          busy={remove.isPending}
          error={remove.error?.message}
          onConfirm={() => remove.mutate(deleting)}
          onCancel={() => setDeleting(null)}
        >
          “{deleting.title}” and its messages will be removed. Your notes are not affected.
        </ConfirmDialog>
      )}
    </section>
  )
}
