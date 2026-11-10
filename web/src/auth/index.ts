import { config } from '../config'
import { createSupabaseAuth } from './supabase'
import type { AuthClient } from './types'

// `import.meta.env.VITE_MOCK` is replaced by a literal at build time. In a
// normal build the first branch is dead code, so the dynamic import (and with
// it everything in src/mock) is left out of the bundle.
export const auth: AuthClient =
  import.meta.env.VITE_MOCK === '1'
    ? (await import('../mock/auth')).createMockAuth()
    : createSupabaseAuth(config.supabaseUrl, config.supabaseAnonKey)
