import '@fontsource-variable/inter'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { configError } from './config'
import './index.css'

const root = createRoot(document.getElementById('root')!)

if (configError) {
  root.render(<p className="mx-auto max-w-prose p-6">{configError}</p>)
} else {
  // Loaded only now: importing the app creates the Supabase client, which
  // cannot be done without its settings.
  const { App } = await import('./App')
  root.render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}
