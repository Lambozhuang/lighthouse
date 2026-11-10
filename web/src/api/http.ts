import { readSse } from './sse'
import {
  ApiError,
  type Api,
  type ChatEvent,
  type ChatMessage,
  type InboxItem,
  type Note,
  type NoteSummary,
  type Thread,
} from './types'

type Options = {
  baseUrl: string
  /** The current session's access token, or null when signed out. */
  getToken: () => Promise<string | null>
  /** Called when the backend answers 401: the session is no longer valid. */
  onUnauthorized: () => void
}

const CHAT_EVENTS = new Set(['thread', 'tool', 'token', 'sources', 'error', 'done'])

/** The real API client: plain fetch calls against the Lighthouse backend. */
export function createHttpApi({ baseUrl, getToken, onUnauthorized }: Options): Api {
  async function request(path: string, init: RequestInit = {}): Promise<Response> {
    const headers = new Headers(init.headers)
    const token = await getToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
    if (init.body) headers.set('Content-Type', 'application/json')

    let response: Response
    try {
      response = await fetch(baseUrl + path, { ...init, headers })
    } catch (error) {
      if (init.signal?.aborted) throw error // cancelled on purpose, not a failure
      throw new ApiError(0, 'Could not reach the server. Check your connection and try again.')
    }
    if (response.ok) return response
    if (response.status === 401) onUnauthorized()
    throw new ApiError(response.status, await errorDetail(response))
  }

  async function json<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await request(path, init)
    return (await response.json()) as T
  }

  return {
    drop: (content) =>
      json<InboxItem>('/api/drop', { method: 'POST', body: JSON.stringify({ content }) }),
    listInbox: () => json<InboxItem[]>('/api/inbox'),
    retryInboxItem: (id) => json<InboxItem>(`/api/inbox/${id}/retry`, { method: 'POST' }),

    listNotes: (query = {}) => {
      const params = new URLSearchParams()
      for (const [key, value] of Object.entries(query)) {
        if (value !== undefined && value !== '') params.set(key, String(value))
      }
      return json<NoteSummary[]>(`/api/notes?${params}`)
    },
    getNote: (id) => json<Note>(`/api/notes/${id}`),
    deleteNote: async (id) => {
      await request(`/api/notes/${id}`, { method: 'DELETE' })
    },

    listThreads: () => json<Thread[]>('/api/threads'),
    listMessages: (threadId) => json<ChatMessage[]>(`/api/threads/${threadId}/messages`),
    deleteThread: async (id) => {
      await request(`/api/threads/${id}`, { method: 'DELETE' })
    },

    async *chat(body, signal) {
      const response = await request('/api/chat', {
        method: 'POST',
        headers: { Accept: 'text/event-stream' },
        body: JSON.stringify(body),
        signal,
      })
      if (!response.body) throw new ApiError(response.status, 'The server sent an empty answer.')
      for await (const message of readSse(response.body)) {
        // Skip event names this version of the app does not know.
        if (CHAT_EVENTS.has(message.event)) {
          yield { event: message.event, data: JSON.parse(message.data) } as ChatEvent
        }
      }
    },
  }
}

/** Errors are `{"detail": "..."}`; anything else gets a generic message. */
async function errorDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json()
    if (typeof body === 'object' && body !== null && 'detail' in body) {
      if (typeof body.detail === 'string') return body.detail
    }
  } catch {
    // Not JSON: fall through to the generic message.
  }
  return `The request failed (${response.status}).`
}
