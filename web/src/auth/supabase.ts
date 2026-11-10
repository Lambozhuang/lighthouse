import { createClient } from '@supabase/supabase-js'
import type { AuthClient } from './types'

/**
 * Supabase is used for auth only: it signs the user in and keeps the session
 * (in localStorage) fresh. All data goes through the Lighthouse API instead.
 */
export function createSupabaseAuth(url: string, anonKey: string): AuthClient {
  const supabase = createClient(url, anonKey)

  return {
    onSessionChange(listener) {
      // Supabase fires INITIAL_SESSION right after subscribing, so there is no
      // separate "load the session" step.
      const { data } = supabase.auth.onAuthStateChange((_event, session) => {
        listener(session ? { email: session.user.email ?? '' } : null)
      })
      return () => data.subscription.unsubscribe()
    },

    async getAccessToken() {
      const { data } = await supabase.auth.getSession()
      return data.session?.access_token ?? null
    },

    async signIn(email, password) {
      const { error } = await supabase.auth.signInWithPassword({ email, password })
      if (error) throw new Error(error.message)
    },

    async signUp(email, password) {
      const { data, error } = await supabase.auth.signUp({ email, password })
      if (error) throw new Error(error.message)
      return { signedIn: data.session !== null }
    },

    async signOut() {
      // "local" ends the session in this browser only, not on other devices.
      await supabase.auth.signOut({ scope: 'local' })
    },
  }
}
