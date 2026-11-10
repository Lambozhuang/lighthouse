// An in-memory fake of the Lighthouse API, used when VITE_MOCK=1.
// It keeps its data in plain arrays, so a page reload starts over from the seed.
//
// Tricks for demos:
// - drop something containing the word "fail" to see a failed inbox item (retry succeeds);
// - send a chat message containing the word "error" to see the stream fail.

import {
  ApiError,
  type Api,
  type ChatEvent,
  type ChatMessage,
  type ChatRequest,
  type InboxItem,
  type Note,
  type NoteSummary,
} from '../api/types'
import * as seed from './data'

const now = () => new Date().toISOString()

/** Waits like a slow network would; rejects if the signal is aborted meanwhile. */
function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    signal?.throwIfAborted()
    const timer = setTimeout(resolve, ms)
    signal?.addEventListener('abort', () => {
      clearTimeout(timer)
      reject(signal.reason)
    })
  })
}

export function createMockApi(): Api {
  const notes = structuredClone(seed.notes)
  const inbox = structuredClone(seed.inbox)
  const threads = structuredClone(seed.threads)
  const messages = structuredClone(seed.messages)
  const failedOnce = new Set<string>()

  /** Answers like the server would: after a short delay, with a copy of the data. */
  async function respond<T>(value: T): Promise<T> {
    await sleep(250)
    return structuredClone(value)
  }

  function find<T extends { id: string }>(items: T[], id: string, what: string): T {
    const item = items.find((candidate) => candidate.id === id)
    if (!item) throw new ApiError(404, `${what} not found`)
    return item
  }

  function remove(items: { id: string }[], id: string, what: string) {
    items.splice(items.indexOf(find(items, id, what)), 1)
  }

  // The background worker: pending → processing → done or failed.
  function process(item: InboxItem, startAfter: number) {
    const update = (patch: Partial<InboxItem>) => Object.assign(item, patch, { updated_at: now() })
    setTimeout(() => update({ status: 'processing' }), startAfter)
    setTimeout(() => {
      if (/\bfail/i.test(item.content) && !failedOnce.has(item.id)) {
        failedOnce.add(item.id)
        update({ status: 'failed', error: 'The page took too long to respond.' })
      } else {
        const note = distill(item)
        notes.unshift(note)
        update({ status: 'done', note_id: note.id })
      }
    }, startAfter + 2500)
  }

  for (const item of inbox) {
    if (item.status === 'pending') process(item, 6000)
  }

  async function* chat(request: ChatRequest, signal: AbortSignal): AsyncGenerator<ChatEvent> {
    await sleep(300, signal)
    let thread = threads.find((candidate) => candidate.id === request.thread_id)
    if (request.thread_id && !thread) throw new ApiError(404, 'Thread not found')
    if (!thread) {
      const title = request.message.slice(0, 60)
      thread = { id: crypto.randomUUID(), title, created_at: now(), updated_at: now() }
      threads.push(thread)
      messages[thread.id] = []
    }
    thread.updated_at = now()
    messages[thread.id].push({ role: 'user', content: request.message, sources: [] })
    yield { event: 'thread', data: { thread_id: thread.id, title: thread.title } }

    await sleep(500, signal)
    if (/\berror\b/i.test(request.message)) {
      const message = 'The model is not available right now. Try again in a moment.'
      yield { event: 'error', data: { message } }
      return
    }

    yield { event: 'tool', data: { name: 'search_notes', input: { query: request.message } } }
    await sleep(900, signal)

    const found = search(notes, request.message)
    const answer = compose(found)
    // Cut into small pieces so that citation markers arrive split across tokens.
    for (const text of answer.match(/[\s\S]{1,7}/g) ?? []) {
      await sleep(30, signal)
      yield { event: 'token', data: { text } }
    }

    const reply: ChatMessage = {
      role: 'assistant',
      content: answer,
      sources: found.map(({ id, title, source_url }) => ({ id, title, source_url })),
    }
    messages[thread.id].push(reply)
    yield { event: 'sources', data: { sources: structuredClone(reply.sources) } }
    yield { event: 'done', data: {} }
  }

  return {
    async drop(content) {
      const trimmed = content.trim()
      const item: InboxItem = {
        id: crypto.randomUUID(),
        kind: /^https?:\/\/\S+$/.test(trimmed) ? 'url' : 'text',
        content: trimmed,
        status: 'pending',
        error: null,
        note_id: null,
        created_at: now(),
        updated_at: now(),
      }
      inbox.unshift(item)
      process(item, 1500)
      return respond(item)
    },
    listInbox: () => respond(inbox),
    async retryInboxItem(id) {
      const item = find(inbox, id, 'Inbox item')
      if (item.status !== 'failed') throw new ApiError(409, 'Only failed items can be retried')
      Object.assign(item, { status: 'pending', error: null, updated_at: now() })
      process(item, 1500)
      return respond(item)
    },

    listNotes({ q = '', tag = '', limit = 50, offset = 0 } = {}) {
      const needle = q.trim().toLowerCase()
      const matches = notes.filter(
        (note) =>
          (!tag || note.tags.includes(tag)) &&
          (!needle || searchableText(note).includes(needle)),
      )
      return respond(matches.slice(offset, offset + limit).map(toSummary))
    },
    getNote: async (id) => respond(find(notes, id, 'Note')),
    async deleteNote(id) {
      remove(notes, id, 'Note')
      await respond(null)
    },

    listThreads: () =>
      respond([...threads].sort((a, b) => b.updated_at.localeCompare(a.updated_at))),
    async listMessages(threadId) {
      find(threads, threadId, 'Thread')
      return respond(messages[threadId])
    },
    async deleteThread(id) {
      remove(threads, id, 'Thread')
      delete messages[id]
      await respond(null)
    },

    chat,
  }
}

function toSummary({ id, title, summary, tags, source_url, created_at }: Note): NoteSummary {
  return { id, title, summary, tags, source_url, created_at }
}

function searchableText(note: Note): string {
  return [note.title, note.summary, note.body, ...note.tags].join('\n').toLowerCase()
}

/** A stand-in for the distill step: wraps the dropped content in a note. */
function distill(item: InboxItem): Note {
  const isUrl = item.kind === 'url'
  const firstLine = item.content.split('\n')[0].slice(0, 60)
  return {
    id: crypto.randomUUID(),
    title: isUrl ? `Page from ${new URL(item.content).hostname}` : firstLine,
    summary: 'A placeholder note. The real backend writes a summary of the content here.',
    tags: ['mock'],
    source_url: isUrl ? item.content : null,
    source_title: null,
    created_at: now(),
    key_points: ['Mock mode does not call a model, so there are no real key points.'],
    body: isUrl ? 'The text of the fetched page would appear here.' : item.content,
  }
}

/** The two notes sharing the most words with the question (or simply the newest two). */
function search(notes: Note[], question: string): Note[] {
  const words = question.toLowerCase().match(/[a-z]{4,}/g) ?? []
  const score = (note: Note) => words.filter((word) => searchableText(note).includes(word)).length
  return [...notes].sort((a, b) => score(b) - score(a)).slice(0, 2)
}

/** A canned answer that cites the notes it was given. */
function compose(found: Note[]): string {
  const [first, second] = found
  if (!first) return 'I could not find anything about that in your notes.'
  const cite = (note: Note) => `[note:${note.id.slice(0, 8)}]`

  const parts = [
    'Here is what your notes say.',
    `**${first.title}.** ${first.summary} ${cite(first)}`,
    first.key_points.map((point) => `- ${point}`).join('\n'),
  ]
  if (second) parts.push(`See also _${second.title}_: ${second.summary} ${cite(second)}`)
  parts.push('This answer was written by mock mode, not by a model.')
  return parts.join('\n\n')
}
