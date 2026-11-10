import type { NotesQuery } from './types'

/** TanStack Query cache keys, in one place so that reads and invalidations agree. */
export const keys = {
  threads: ['threads'],
  messages: (threadId: string) => ['messages', threadId],
  inbox: ['inbox'],
  /** `keys.notes()` is the prefix of every notes list, whatever its filters. */
  notes: (query?: NotesQuery) => (query ? ['notes', query] : ['notes']),
  note: (id: string) => ['note', id],
} as const
