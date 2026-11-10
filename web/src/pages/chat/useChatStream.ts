import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { api, type ChatMessage, type Source } from '../../api'
import { keys } from '../../api/keys'
import { errorMessage } from '../../lib/format'

/** A message as the chat page shows it: the API's ChatMessage plus how its stream went. */
export type UiMessage = {
  role: ChatMessage['role']
  content: string
  /** null when the stream ended before its `sources` event (stopped or failed). */
  sources: Source[] | null
  /** What the agent did before answering. Only known for turns streamed in this session. */
  activity?: string[]
  /** The stream failed; this is the reason. */
  error?: string
  /** The stream was cancelled before the answer was complete. */
  stopped?: boolean
}

/** The turn that is being streamed right now. */
export type LiveTurn = {
  /** null in a new chat until the server's `thread` event names the thread. */
  threadId: string | null
  question: string
  /** The answer so far. */
  answer: string
  /** What the agent has done so far, for example "Searching notes: pgvector". */
  activity: string[]
  /** null until the `sources` event, which comes after the last token. */
  sources: Source[] | null
  /** Set only when a new chat failed before it got a thread to be saved in. */
  error: string | null
}

type ActiveStream = { controller: AbortController; threadId: string | null }

/**
 * Sends chat messages and follows the answer as it streams in.
 *
 * While a turn is streaming it lives in this hook's state. When it ends (done,
 * failed or stopped) it is appended to the cached history of its thread, so
 * the page has a single list to render again.
 *
 * @param routeThreadId the thread in the URL, or null on the new-chat page
 */
export function useChatStream(routeThreadId: string | null) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [turn, setTurn] = useState<LiveTurn | null>(null)
  const active = useRef<ActiveStream | null>(null)

  // Leaving a thread (or the chat page) cancels the stream that belongs to it.
  // When a new chat gets its id, the stream's threadId is updated before the URL
  // changes, so that move from "/chat" to "/chat/<id>" does not count as leaving.
  useEffect(() => {
    return () => {
      const stream = active.current
      if (stream?.threadId === routeThreadId) stream.controller.abort()
      // No stream at all: anything still on screen is a failed turn. Drop it.
      if (!stream) setTurn(null)
    }
  }, [routeThreadId])

  async function send(message: string) {
    const stream: ActiveStream = { controller: new AbortController(), threadId: routeThreadId }
    const { signal } = stream.controller
    active.current = stream

    let current: LiveTurn = {
      threadId: routeThreadId,
      question: message,
      answer: '',
      activity: [],
      sources: null,
      error: null,
    }
    const show = (patch: Partial<LiveTurn>) => {
      current = { ...current, ...patch }
      // Once another stream has started, this one no longer owns the screen.
      if (active.current === stream) setTurn(current)
    }
    show({})

    let error: string | undefined
    let ended = false // the server said `done` or `error`
    try {
      const request = { message, thread_id: routeThreadId ?? undefined }
      for await (const { event, data } of api.chat(request, signal)) {
        switch (event) {
          case 'thread':
            if (!current.threadId) {
              stream.threadId = data.thread_id
              // The new thread starts with an empty cached history, so nothing
              // is fetched for it while this turn is still streaming.
              queryClient.setQueryData<UiMessage[]>(keys.messages(data.thread_id), [])
              show({ threadId: data.thread_id })
              // flushSync: the URL and the turn switch to the new thread in one render.
              void navigate(`/chat/${data.thread_id}`, { replace: true, flushSync: true })
            }
            void queryClient.invalidateQueries({ queryKey: keys.threads })
            break
          case 'tool':
            show({ activity: [...current.activity, describeTool(data.name, data.input)] })
            break
          case 'token':
            show({ answer: current.answer + data.text })
            break
          case 'sources':
            show({ sources: data.sources })
            break
          case 'error':
            error = data.message
            ended = true
            break
          case 'done':
            ended = true
            break
        }
      }
      if (!ended) error = 'The connection closed before the answer was complete.'
    } catch (cause) {
      // An abort also lands here; it is reported as "stopped", not as an error.
      if (!signal.aborted) error = errorMessage(cause)
    }

    const { threadId } = current
    if (threadId) {
      const stopped = signal.aborted && !ended
      queryClient.setQueryData<UiMessage[]>(keys.messages(threadId), (history = []) => [
        ...history,
        { role: 'user', content: message, sources: [] },
        {
          role: 'assistant',
          content: current.answer,
          sources: current.sources,
          activity: current.activity,
          error,
          stopped,
        },
      ])
      void queryClient.invalidateQueries({ queryKey: keys.threads })
    }
    if (active.current === stream) {
      active.current = null
      // Without a thread there is no history to move the turn into. Keep a
      // failed one on screen so that its error can be read.
      setTurn(!threadId && error ? { ...current, error } : null)
    }
  }

  function stop() {
    active.current?.controller.abort()
  }

  // Show the turn only on the thread it belongs to.
  const visible = turn && turn.threadId === routeThreadId ? turn : null
  return {
    turn: visible,
    streaming: visible !== null && visible.error === null,
    send,
    stop,
  }
}

function describeTool(name: string, input: Record<string, unknown>): string {
  if (name === 'search_notes') {
    return typeof input.query === 'string' ? `Searching notes: ${input.query}` : 'Searching notes'
  }
  if (name === 'get_note') return 'Reading a note'
  return `Using ${name}`
}
