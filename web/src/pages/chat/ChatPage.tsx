import { useQuery } from '@tanstack/react-query'
import { useLayoutEffect, useRef, type RefObject } from 'react'
import { Link, useParams } from 'react-router'
import { api } from '../../api'
import { keys } from '../../api/keys'
import { Answer } from '../../components/Answer'
import { ErrorNote, Spinner } from '../../components/ui'
import { Composer } from './Composer'
import { useChatStream, type LiveTurn, type UiMessage } from './useChatStream'

/** A conversation: `/chat` starts a new one, `/chat/:threadId` continues one. */
export function ChatPage() {
  const threadId = useParams().threadId ?? null
  const history = useQuery<UiMessage[]>({
    queryKey: keys.messages(threadId ?? 'new'),
    queryFn: () => api.listMessages(threadId!),
    enabled: threadId !== null,
    // Finished turns are appended to this cache by useChatStream, so the
    // history is fetched once per thread and then kept up to date locally.
    staleTime: Infinity,
  })
  const { turn, streaming, send, stop } = useChatStream(threadId)
  const messages = threadId ? history.data : []
  const scrollArea = useRef<HTMLDivElement>(null)
  const scrolling = useStickToBottom(scrollArea, threadId)

  return (
    <div className="flex h-full flex-col">
      <div ref={scrollArea} onScroll={scrolling.onScroll} className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-6 sm:px-6 md:py-8">
          {messages === undefined ? (
            history.isError ? (
              <ErrorNote message={history.error.message} onRetry={() => void history.refetch()} />
            ) : (
              <Spinner label="Loading messages" />
            )
          ) : messages.length === 0 && !turn ? (
            <Welcome />
          ) : (
            messages.map((message, index) =>
              message.role === 'user' ? (
                <UserMessage key={index} text={message.content} />
              ) : (
                <AssistantMessage key={index} message={message} />
              ),
            )
          )}
          {turn && <StreamingTurn turn={turn} streaming={streaming} />}
        </div>
      </div>

      <Composer
        streaming={streaming}
        disabled={messages === undefined}
        onStop={stop}
        onSend={(message) => {
          scrolling.stick()
          void send(message)
        }}
      />
    </div>
  )
}

function Welcome() {
  return (
    <div className="pt-[12vh]">
      <h1 className="text-2xl font-semibold tracking-tight">Ask your notes</h1>
      <p className="mt-2 max-w-prose text-muted">
        Answers come from the notes in your library, with a link to each note they rely on.
        Nothing there yet? Drop a link or some text into the{' '}
        <Link to="/inbox" className="text-accent underline underline-offset-2">
          inbox
        </Link>
        .
      </p>
    </div>
  )
}

function UserMessage({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <p className="max-w-[85%] rounded-2xl bg-panel px-4 py-2.5 wrap-anywhere whitespace-pre-wrap">
        {text}
      </p>
    </div>
  )
}

function AssistantMessage({ message }: { message: UiMessage }) {
  return (
    <div className="flex flex-col gap-3">
      {message.activity?.map((step, index) => <ActivityLine key={index}>{step}</ActivityLine>)}
      {message.content && <Answer text={message.content} sources={message.sources} />}
      {message.stopped && <p className="text-sm text-muted">Stopped.</p>}
      {message.error && <ErrorNote message={message.error} />}
    </div>
  )
}

/** A quiet line saying what the agent did, such as "Searching notes: pgvector". */
function ActivityLine({ children }: { children: string }) {
  return <p className="text-sm text-muted">{children}</p>
}

/** The turn in progress: the question, what the agent is doing, and the answer so far. */
function StreamingTurn({ turn, streaming }: { turn: LiveTurn; streaming: boolean }) {
  const waiting = streaming && turn.answer === ''
  const lastStep = turn.activity.at(-1)
  return (
    <>
      <UserMessage text={turn.question} />
      <div className="flex flex-col gap-3" aria-live="polite" aria-busy={streaming}>
        {turn.activity.slice(0, waiting ? -1 : undefined).map((step, index) => (
          <ActivityLine key={index}>{step}</ActivityLine>
        ))}
        {waiting && <Spinner label={lastStep ?? 'Thinking'} />}
        {turn.answer && <Answer text={turn.answer} sources={turn.sources} streaming={streaming} />}
        {turn.error && <ErrorNote message={turn.error} />}
      </div>
    </>
  )
}

/**
 * Keeps a scrolling element at its bottom while content is added, unless the
 * user has scrolled up to read something. `resetKey` changing (another thread)
 * sticks it to the bottom again.
 */
function useStickToBottom(ref: RefObject<HTMLElement | null>, resetKey: unknown) {
  const stuck = useRef(true)

  useLayoutEffect(() => {
    stuck.current = true
  }, [resetKey])

  // No dependency list: runs after every render, which is when content can have grown.
  useLayoutEffect(() => {
    const element = ref.current
    if (element && stuck.current) element.scrollTop = element.scrollHeight
  })

  return {
    onScroll: () => {
      const element = ref.current
      if (!element) return
      stuck.current = element.scrollHeight - element.scrollTop - element.clientHeight < 80
    },
    stick: () => {
      stuck.current = true
    },
  }
}
