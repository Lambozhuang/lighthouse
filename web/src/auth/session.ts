import { createContext, useContext } from 'react'
import type { Session } from './types'

/** The signed-in user, or null. Provided by `AuthProvider`. */
export const SessionContext = createContext<Session | null>(null)

export function useSession(): Session | null {
  return useContext(SessionContext)
}
