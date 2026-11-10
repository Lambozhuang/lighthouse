import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createBrowserRouter, Link, Navigate, RouterProvider } from 'react-router'
import { ApiError } from './api'
import { AuthProvider } from './auth/AuthProvider'
import { AppShell } from './components/AppShell'
import { Page } from './components/ui'
import { ChatPage } from './pages/chat/ChatPage'
import { InboxPage } from './pages/InboxPage'
import { NotePage } from './pages/NotePage'
import { NotesPage } from './pages/NotesPage'
import { SignInPage } from './pages/SignInPage'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Retry once when the network or the server fails, but not when the
      // server said no (401, 404, ...): asking again gives the same answer.
      retry: (failures, error) =>
        failures < 1 && !(error instanceof ApiError && error.status >= 400 && error.status < 500),
    },
  },
})

const router = createBrowserRouter([
  { path: '/login', element: <SignInPage /> },
  {
    // Everything under AppShell needs a session.
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/chat" replace /> },
      // One route for a new chat and an existing one, so the page (and a stream
      // in progress) stays mounted when a new chat gets its thread id.
      { path: 'chat/:threadId?', element: <ChatPage /> },
      { path: 'inbox', element: <InboxPage /> },
      { path: 'notes', element: <NotesPage /> },
      { path: 'notes/:noteId', element: <NotePage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </QueryClientProvider>
  )
}

function NotFoundPage() {
  return (
    <Page title="Page not found">
      <p className="text-muted">
        There is nothing at this address.{' '}
        <Link to="/chat" className="text-accent underline underline-offset-2">
          Go to chat
        </Link>
      </p>
    </Page>
  )
}
