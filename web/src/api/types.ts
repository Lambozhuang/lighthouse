// The backend contract, mirrored from docs/API.md (and src/lighthouse/schemas.py).
// Ids are UUIDs, timestamps are ISO 8601 UTC strings.

export type InboxStatus = 'pending' | 'processing' | 'done' | 'failed'

export type InboxItem = {
  id: string
  kind: 'text' | 'url'
  /** The pasted text, or the URL. */
  content: string
  status: InboxStatus
  /** Human-readable reason when the status is `failed`. */
  error: string | null
  /** Set when the status is `done`. */
  note_id: string | null
  created_at: string
  updated_at: string
}

export type NoteSummary = {
  id: string
  title: string
  summary: string
  tags: string[]
  source_url: string | null
  created_at: string
}

export type Note = NoteSummary & {
  key_points: string[]
  source_title: string | null
  body: string
}

export type Thread = {
  id: string
  title: string
  created_at: string
  updated_at: string
}

/** A note the agent retrieved while answering. */
export type Source = {
  id: string
  title: string
  source_url: string | null
}

export type ChatMessage = {
  role: 'user' | 'assistant'
  content: string
  sources: Source[]
}

export type ChatRequest = {
  message: string
  /** Omit to start a new thread. */
  thread_id?: string
}

/** One server-sent event of the `POST /api/chat` stream. */
export type ChatEvent =
  | { event: 'thread'; data: { thread_id: string; title: string } }
  | { event: 'tool'; data: { name: string; input: Record<string, unknown> } }
  | { event: 'token'; data: { text: string } }
  | { event: 'sources'; data: { sources: Source[] } }
  | { event: 'error'; data: { message: string } }
  | { event: 'done'; data: Record<string, never> }

export type NotesQuery = {
  q?: string
  tag?: string
  limit?: number
  offset?: number
}

/**
 * Everything the app asks of the backend. There are two implementations:
 * `createHttpApi` (the real one) and `createMockApi` (in memory, for `VITE_MOCK=1`).
 */
export interface Api {
  drop(content: string): Promise<InboxItem>
  listInbox(): Promise<InboxItem[]>
  retryInboxItem(id: string): Promise<InboxItem>
  listNotes(query?: NotesQuery): Promise<NoteSummary[]>
  getNote(id: string): Promise<Note>
  deleteNote(id: string): Promise<void>
  listThreads(): Promise<Thread[]>
  listMessages(threadId: string): Promise<ChatMessage[]>
  deleteThread(id: string): Promise<void>
  /** Streams one chat turn. Abort the signal to cancel it. */
  chat(request: ChatRequest, signal: AbortSignal): AsyncGenerator<ChatEvent>
}

/** A failed API call, with the backend's `detail` as the message. */
export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}
