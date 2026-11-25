import { useState, type FormEvent } from 'react'
import { Navigate, useLocation } from 'react-router'
import { auth } from '../auth'
import { useSession } from '../auth/session'
import { LogoIcon } from '../components/icons'
import { Button, fieldClass } from '../components/ui'
import { config } from '../config'
import { errorMessage } from '../lib/format'

/** Sign in. There is no sign-up form: accounts are created on the server (scripts/create_user.py). */
export function SignInPage() {
  const session = useSession()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (session) {
    const from: unknown = location.state?.from
    return <Navigate to={typeof from === 'string' ? from : '/'} replace />
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await auth.signIn(email, password)
      // On success the session changes and this page redirects (see above).
    } catch (cause) {
      setError(errorMessage(cause))
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="grid min-h-dvh place-items-center px-4 py-10">
      <div className="flex w-full max-w-sm flex-col gap-6">
        <header>
          <div className="flex items-center gap-2 text-accent">
            <LogoIcon size={26} />
            <span className="text-lg font-semibold tracking-tight text-ink">Lighthouse</span>
          </div>
          <h1 className="mt-6 text-2xl font-semibold tracking-tight">Sign in</h1>
          <p className="mt-1 text-muted">Your notes, and an agent that answers from them.</p>
        </header>

        <form onSubmit={submit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="email" className="text-sm font-medium">
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className={fieldClass}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="password" className="text-sm font-medium">
              Password
            </label>
            <input
              id="password"
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className={fieldClass}
            />
          </div>

          {error && (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          )}

          <Button type="submit" variant="primary" disabled={busy}>
            {busy ? 'One moment…' : 'Sign in'}
          </Button>
        </form>

        {config.mock && (
          <p className="rounded-md border border-dashed border-line px-3 py-2 text-sm text-muted">
            Mock mode: any email and password work, and nothing leaves this browser.
          </p>
        )}
      </div>
    </main>
  )
}
