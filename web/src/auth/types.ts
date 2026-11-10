export type Session = {
  email: string
}

/**
 * What the app needs from an auth provider. The real implementation wraps
 * Supabase Auth (`supabase.ts`); mock mode has its own (`src/mock/auth.ts`).
 */
export interface AuthClient {
  /**
   * Calls the listener with the current session (null when signed out) shortly
   * after subscribing, then again on every change. Returns an unsubscribe function.
   */
  onSessionChange(listener: (session: Session | null) => void): () => void
  /** The token to send as `Authorization: Bearer`, refreshed if it had expired. */
  getAccessToken(): Promise<string | null>
  signIn(email: string, password: string): Promise<void>
  /** `signedIn` is false when the account must be confirmed by email first. */
  signUp(email: string, password: string): Promise<{ signedIn: boolean }>
  signOut(): Promise<void>
}
