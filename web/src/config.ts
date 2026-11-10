// Settings come from VITE_* variables at build time (see .env.example).
// Everything here is public: it is compiled into the JavaScript bundle.

const env = import.meta.env

export const config = {
  /** Run against the in-memory fake in src/mock instead of a real backend. */
  mock: env.VITE_MOCK === '1',
  apiUrl: (env.VITE_API_URL || 'http://localhost:8080').replace(/\/+$/, ''),
  supabaseUrl: env.VITE_SUPABASE_URL || 'http://localhost:8000',
  supabaseAnonKey: env.VITE_SUPABASE_ANON_KEY || '',
}

/** A message for the developer when the app cannot start, otherwise null. */
export const configError =
  !config.mock && !config.supabaseAnonKey
    ? 'VITE_SUPABASE_ANON_KEY is not set. Copy .env.example to .env.local and fill it in, or run `pnpm dev:mock` to try the app without a backend.'
    : null
