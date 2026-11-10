import { useEffect, useRef, type ReactNode } from 'react'
import { Button } from './ui'

type Props = {
  title: string
  children: ReactNode
  confirmLabel: string
  /** The action is running: both buttons are disabled. */
  busy?: boolean
  error?: string | null
  onConfirm: () => void
  onCancel: () => void
}

/**
 * A modal question before something is deleted. Render it only while it should
 * be open. The native <dialog> traps focus and closes on Escape by itself.
 */
export function ConfirmDialog({ title, children, confirmLabel, busy, error, onConfirm, onCancel }: Props) {
  const ref = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    ref.current?.showModal()
  }, [])

  return (
    <dialog
      ref={ref}
      aria-labelledby="confirm-title"
      onClose={onCancel}
      // A click on the backdrop lands on the <dialog> element itself.
      onClick={(event) => event.target === event.currentTarget && onCancel()}
      className="m-auto w-[min(26rem,calc(100vw-2rem))] rounded-lg border border-line bg-canvas text-ink shadow-xl"
    >
      <div className="flex flex-col gap-2 p-5">
        <h2 id="confirm-title" className="text-base font-semibold">
          {title}
        </h2>
        <div className="text-muted">{children}</div>
        {error && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}
        <div className="mt-3 flex justify-end gap-2">
          <Button onClick={onCancel} disabled={busy} autoFocus>
            Cancel
          </Button>
          <Button variant="danger" onClick={onConfirm} disabled={busy}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </dialog>
  )
}
