// A small parser for server-sent events (the `text/event-stream` format).
//
// The browser's EventSource cannot send a POST body or an Authorization header,
// so the chat stream is read with fetch and parsed here. The network delivers
// the stream in arbitrary chunks: an event, a line or even a single character
// can be cut in half, so the parser keeps the unfinished tail between chunks.

export type SseMessage = {
  /** The `event:` field, or "message" when the event has none. */
  event: string
  /** The `data:` field. Several data lines are joined with "\n". */
  data: string
}

/** A line ends with \r\n, \n or \r. A \r at the very end may be half of a \r\n, so it waits. */
const LINE_BREAK = /\r\n|\n|\r(?!$)/

export function createSseParser() {
  let buffer = ''
  let event = ''
  let data: string[] = []

  /** Feed the next piece of text; returns the events it completed. */
  function feed(chunk: string): SseMessage[] {
    const messages: SseMessage[] = []
    const lines = (buffer + chunk).split(LINE_BREAK)
    buffer = lines.pop() ?? '' // the last piece has no line break yet

    for (const line of lines) {
      if (line === '') {
        // A blank line ends the event.
        if (data.length > 0) {
          messages.push({ event: event || 'message', data: data.join('\n') })
        }
        event = ''
        data = []
      } else if (!line.startsWith(':')) {
        // "field: value", where the space after the colon is optional. Lines
        // that start with a colon are comments, often sent as keep-alives.
        const colon = line.indexOf(':')
        const field = colon === -1 ? line : line.slice(0, colon)
        let value = colon === -1 ? '' : line.slice(colon + 1)
        if (value.startsWith(' ')) value = value.slice(1)

        if (field === 'event') event = value
        else if (field === 'data') data.push(value)
        // `id` and `retry` are not used by this app.
      }
    }
    return messages
  }

  return { feed }
}

/** Reads a response body and yields its events as they complete. */
export async function* readSse(body: ReadableStream<Uint8Array>): AsyncGenerator<SseMessage> {
  const parser = createSseParser()
  // `stream: true` keeps a multi-byte character that is split across chunks.
  const decoder = new TextDecoder()
  const reader = body.getReader()
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      yield* parser.feed(decoder.decode(value, { stream: true }))
    }
  } finally {
    reader.releaseLock()
  }
}
