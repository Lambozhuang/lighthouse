// Small building blocks shared by the pages.

import type { ComponentProps, ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router'
import { cx, webUrl } from '../lib/format'
import { ExternalIcon } from './icons'

const buttonVariants = {
  primary: 'bg-accent text-on-accent hover:bg-accent/90',
  secondary: 'border border-line hover:bg-panel',
  ghost: 'text-muted hover:bg-hover hover:text-ink',
  danger: 'bg-danger text-on-accent hover:bg-danger/90',
}

const buttonBase =
  'inline-flex shrink-0 items-center justify-center gap-2 rounded-md text-sm font-medium transition-colors disabled:opacity-50'

type ButtonProps = ComponentProps<'button'> & { variant?: keyof typeof buttonVariants }

export function Button({ variant = 'secondary', className, type = 'button', ...props }: ButtonProps) {
  return (
    <button
      type={type}
      className={cx(buttonBase, 'h-10 px-4', buttonVariants[variant], className)}
      {...props}
    />
  )
}

type IconButtonProps = ButtonProps & {
  /** What the button does, for screen readers and as a tooltip. */
  label: string
  small?: boolean
}

/** A square button that shows only an icon. */
export function IconButton({
  label,
  small = false,
  variant = 'ghost',
  className,
  type = 'button',
  ...props
}: IconButtonProps) {
  return (
    <button
      type={type}
      aria-label={label}
      title={label}
      className={cx(buttonBase, small ? 'size-8' : 'size-10', buttonVariants[variant], className)}
      {...props}
    />
  )
}

/** Shared look of text inputs and textareas. The focus outline sits on top of the border. */
export const fieldClass =
  'w-full rounded-md border border-line bg-canvas px-3 py-2 -outline-offset-1'

export function Spinner({ label }: { label: string }) {
  return (
    <span role="status" className="inline-flex items-center gap-2 text-sm text-muted">
      <span className="size-3.5 animate-spin rounded-full border-2 border-line border-t-muted motion-reduce:animate-none" />
      {label}…
    </span>
  )
}

/** An error message with an optional way to try again. */
export function ErrorNote({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <p className="text-danger">{message}</p>
      {onRetry && <Button onClick={onRetry}>Try again</Button>}
    </div>
  )
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-md border border-dashed border-line px-5 py-6">
      <p className="font-medium">{title}</p>
      {children && <p className="mt-1 text-muted">{children}</p>}
    </div>
  )
}

/** The scrolling, centered column used by every page except chat. */
export function Page({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-6 sm:px-6 md:py-10">
        <h1 className="text-2xl font-semibold tracking-tight text-balance">{title}</h1>
        {children}
      </div>
    </div>
  )
}

/** A tag that filters the notes list when clicked; clicking the active tag clears the filter. */
export function TagLink({ tag, active = false }: { tag: string; active?: boolean }) {
  // On the notes page a search may be in the URL; keep it when the tag changes.
  const [params] = useSearchParams()
  const next = new URLSearchParams()
  const q = params.get('q')
  if (q) next.set('q', q)
  if (!active) next.set('tag', tag)

  return (
    <Link
      to={{ pathname: '/notes', search: next.toString() }}
      aria-current={active ? 'true' : undefined}
      className={cx(
        'rounded-md px-2 py-1 text-xs font-medium transition-colors',
        active ? 'bg-accent text-on-accent' : 'bg-panel text-muted hover:bg-hover hover:text-ink',
      )}
    >
      {tag}
    </Link>
  )
}

/** A link to where a note came from. Renders nothing unless the URL is http(s). */
export function SourceLink({ url, title }: { url: string | null; title?: string | null }) {
  const parsed = webUrl(url)
  if (!parsed) return null
  return (
    <a
      href={parsed.href}
      target="_blank"
      rel="noreferrer"
      className="inline-flex min-w-0 items-center gap-1 text-muted underline-offset-2 hover:text-ink hover:underline"
    >
      <span className="truncate">{title || parsed.hostname}</span>
      <ExternalIcon size={14} />
    </a>
  )
}
