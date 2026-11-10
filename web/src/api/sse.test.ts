import { describe, expect, it } from 'vitest'
import { createSseParser, readSse, type SseMessage } from './sse'

/** Feeds the chunks one by one and collects every event. */
function parse(chunks: string[]): SseMessage[] {
  const parser = createSseParser()
  return chunks.flatMap((chunk) => parser.feed(chunk))
}

const stream = [
  'event: thread\ndata: {"thread_id":"t1","title":"Hello"}\n\n',
  'event: token\ndata: {"text":"Hi"}\n\n',
  'event: done\ndata: {}\n\n',
].join('')

const expected: SseMessage[] = [
  { event: 'thread', data: '{"thread_id":"t1","title":"Hello"}' },
  { event: 'token', data: '{"text":"Hi"}' },
  { event: 'done', data: '{}' },
]

describe('createSseParser', () => {
  it('parses several events from one chunk', () => {
    expect(parse([stream])).toEqual(expected)
  })

  it('gives the same result however the stream is cut into chunks', () => {
    for (let size = 1; size <= stream.length; size++) {
      const chunks: string[] = []
      for (let i = 0; i < stream.length; i += size) chunks.push(stream.slice(i, i + size))
      expect(parse(chunks), `chunk size ${size}`).toEqual(expected)
    }
  })

  it('emits an event only once its blank line arrives', () => {
    const parser = createSseParser()
    expect(parser.feed('event: token\ndata: {"text":"a"}\n')).toEqual([])
    expect(parser.feed('\n')).toEqual([{ event: 'token', data: '{"text":"a"}' }])
  })

  it('accepts \\r\\n and \\r line endings, also when \\r\\n is split', () => {
    expect(parse(['event: a\r\ndata: 1\r\n\r\n'])).toEqual([{ event: 'a', data: '1' }])
    // A trailing \r is held back until the next character shows it is not a \r\n.
    expect(parse(['event: a\rdata: 1\r\rdata: 2\r\r', ': end'])).toEqual([
      { event: 'a', data: '1' },
      { event: 'message', data: '2' },
    ])
    expect(parse(['event: a\r', '\ndata: 1\r', '\n\r', '\n'])).toEqual([{ event: 'a', data: '1' }])
  })

  it('joins multiple data lines with a newline', () => {
    expect(parse(['data: one\ndata: two\n\n'])).toEqual([{ event: 'message', data: 'one\ntwo' }])
  })

  it('strips at most one space after the colon', () => {
    expect(parse(['data:no space\n\n', 'data:  two spaces\n\n'])).toEqual([
      { event: 'message', data: 'no space' },
      { event: 'message', data: ' two spaces' },
    ])
  })

  it('ignores comments, unknown fields and events without data', () => {
    const chunks = [': keep-alive\n\n', 'id: 7\nretry: 1000\nevent: empty\n\n', 'data: x\n\n']
    expect(parse(chunks)).toEqual([{ event: 'message', data: 'x' }])
  })

  it('does not carry the event name over to the next event', () => {
    expect(parse(['event: a\ndata: 1\n\ndata: 2\n\n'])).toEqual([
      { event: 'a', data: '1' },
      { event: 'message', data: '2' },
    ])
  })

  it('drops an unfinished event at the end of the stream', () => {
    expect(parse(['data: complete\n\ndata: cut off'])).toEqual([
      { event: 'message', data: 'complete' },
    ])
  })
})

describe('readSse', () => {
  function streamOf(chunks: Uint8Array[]): ReadableStream<Uint8Array> {
    return new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(chunk)
        controller.close()
      },
    })
  }

  it('decodes a multi-byte character that is split across chunks', async () => {
    const bytes = new TextEncoder().encode('event: token\ndata: {"text":"café"}\n\n')
    const cut = bytes.indexOf(0xc3) + 1 // "é" is the two bytes c3 a9; cut between them
    const messages: SseMessage[] = []
    for await (const message of readSse(streamOf([bytes.slice(0, cut), bytes.slice(cut)]))) {
      messages.push(message)
    }
    expect(messages).toEqual([{ event: 'token', data: '{"text":"café"}' }])
  })
})
