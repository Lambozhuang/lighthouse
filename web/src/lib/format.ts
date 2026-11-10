const dateFormat = new Intl.DateTimeFormat('en', { dateStyle: 'medium' })
const relativeFormat = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })

/** "Nov 10, 2026" */
export function formatDate(iso: string): string {
  return dateFormat.format(new Date(iso))
}

/** "just now", "5 minutes ago", "yesterday"; a plain date after a week. */
export function timeAgo(iso: string): string {
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return relativeFormat.format(-Math.floor(seconds / 60), 'minute')
  if (seconds < 86_400) return relativeFormat.format(-Math.floor(seconds / 3600), 'hour')
  if (seconds < 7 * 86_400) return relativeFormat.format(-Math.floor(seconds / 86_400), 'day')
  return formatDate(iso)
}

/**
 * Parses a URL that came from a note. Returns null unless it is http(s), so
 * that something like a `javascript:` URL can never end up in an href.
 */
export function webUrl(url: string | null): URL | null {
  if (!url || !URL.canParse(url)) return null
  const parsed = new URL(url)
  return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed : null
}

/** Joins class names, skipping the falsy ones: `cx('a', active && 'b')`. */
export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(' ')
}

/** A message to show for anything caught in a `catch`. */
export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong.'
}
