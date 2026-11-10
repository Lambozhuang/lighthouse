import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type ReactNode } from 'react'
import { Spinner } from '../components/ui'
import { auth } from './index'
import { SessionContext } from './session'
import type { Session } from './types'

/** Tracks the auth session and makes it available through `useSession`. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  // undefined: the stored session has not been restored yet.
  const [session, setSession] = useState<Session | null | undefined>(undefined)

  useEffect(() => {
    return auth.onSessionChange((next) => {
      // Nothing fetched for one user may be shown to the next one.
      if (!next) queryClient.clear()
      setSession(next)
    })
  }, [queryClient])

  if (session === undefined) {
    return (
      <div className="grid h-dvh place-items-center">
        <Spinner label="Loading" />
      </div>
    )
  }
  return <SessionContext value={session}>{children}</SessionContext>
}
