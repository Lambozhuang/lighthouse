import { useLayoutEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { SendIcon, StopIcon } from '../../components/icons'
import { IconButton } from '../../components/ui'

type Props = {
  /** An answer is streaming: the send button turns into a stop button. */
  streaming: boolean
  disabled?: boolean
  onSend: (message: string) => void
  onStop: () => void
}

/** The message box. Enter sends, Shift+Enter starts a new line. */
export function Composer({ streaming, disabled = false, onSend, onStop }: Props) {
  const [text, setText] = useState('')
  const textarea = useRef<HTMLTextAreaElement>(null)
  const canSend = !streaming && !disabled && text.trim() !== ''

  // Grow with the text (up to the max height set in CSS).
  useLayoutEffect(() => {
    const element = textarea.current
    if (!element) return
    element.style.height = 'auto'
    element.style.height = `${element.scrollHeight}px`
  }, [text])

  function submit(event?: FormEvent) {
    event?.preventDefault()
    if (!canSend) return
    onSend(text.trim())
    setText('')
  }

  function onKeyDown(event: KeyboardEvent) {
    // isComposing: Enter is confirming an input method's suggestion, not sending.
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <form onSubmit={submit} className="mx-auto w-full max-w-3xl shrink-0 px-4 pb-4 sm:px-6">
      <div className="flex items-end gap-2 rounded-xl border border-line bg-canvas p-1.5 transition-colors focus-within:border-accent">
        <label htmlFor="message" className="sr-only">
          Message
        </label>
        <textarea
          id="message"
          ref={textarea}
          rows={1}
          maxLength={20_000}
          placeholder="Ask about your notes"
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={onKeyDown}
          className="max-h-48 min-w-0 flex-1 resize-none self-center bg-transparent px-2.5 py-1.5 outline-none"
        />
        {streaming ? (
          <IconButton label="Stop" variant="secondary" onClick={onStop}>
            <StopIcon />
          </IconButton>
        ) : (
          <IconButton label="Send" variant="primary" type="submit" disabled={!canSend}>
            <SendIcon />
          </IconButton>
        )}
      </div>
    </form>
  )
}
