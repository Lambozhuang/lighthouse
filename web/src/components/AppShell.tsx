import { useState } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router'
import { useSession } from '../auth/session'
import { MenuIcon } from './icons'
import { Sidebar } from './Sidebar'
import { IconButton } from './ui'

/**
 * The frame around every signed-in page: the sidebar and the page next to it.
 * Without a session it redirects to the sign-in page instead.
 */
export function AppShell() {
  const session = useSession()
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)

  if (!session) {
    // Remember where the user was going, to return there after signing in.
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  }

  return (
    <div
      className="flex h-dvh"
      onKeyDown={(event) => event.key === 'Escape' && setMenuOpen(false)}
    >
      {menuOpen && (
        <div
          aria-hidden="true"
          className="fixed inset-0 z-30 bg-scrim md:hidden"
          onClick={() => setMenuOpen(false)}
        />
      )}
      <Sidebar email={session.email} open={menuOpen} onNavigate={() => setMenuOpen(false)} />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-1 border-b border-line px-2 md:hidden">
          <IconButton label="Open menu" onClick={() => setMenuOpen(true)}>
            <MenuIcon />
          </IconButton>
          <span className="font-semibold tracking-tight">Lighthouse</span>
        </header>
        <main className="min-h-0 flex-1">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
