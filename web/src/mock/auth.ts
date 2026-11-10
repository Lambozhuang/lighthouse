// A fake of the auth provider, used when VITE_MOCK=1. Any email and password
// sign in, except the password "wrong", which shows the error state.

import type { AuthClient, Session } from '../auth/types'

const STORAGE_KEY = 'lighthouse.mock.email'

export function createMockAuth(): AuthClient {
  const listeners = new Set<(session: Session | null) => void>()
  let email = localStorage.getItem(STORAGE_KEY)

  const session = (): Session | null => (email ? { email } : null)

  function setEmail(next: string | null) {
    email = next
    if (next) localStorage.setItem(STORAGE_KEY, next)
    else localStorage.removeItem(STORAGE_KEY)
    for (const listener of listeners) listener(session())
  }

  async function signIn(nextEmail: string, password: string) {
    await new Promise((resolve) => setTimeout(resolve, 400))
    if (password === 'wrong') throw new Error('Invalid login credentials')
    setEmail(nextEmail)
  }

  return {
    onSessionChange(listener) {
      listeners.add(listener)
      // Report the current session a moment later, like Supabase does.
      queueMicrotask(() => {
        if (listeners.has(listener)) listener(session())
      })
      return () => {
        listeners.delete(listener)
      }
    },
    getAccessToken: async () => (email ? 'mock-access-token' : null),
    signIn,
    async signUp(nextEmail, password) {
      await signIn(nextEmail, password)
      return { signedIn: true }
    },
    async signOut() {
      setEmail(null)
    },
  }
}
