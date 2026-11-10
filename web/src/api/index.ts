import { auth } from '../auth'
import { config } from '../config'
import { createHttpApi } from './http'
import type { Api } from './types'

export * from './types'

// As in src/auth/index.ts: a normal build leaves src/mock out of the bundle.
export const api: Api =
  import.meta.env.VITE_MOCK === '1'
    ? (await import('../mock/api')).createMockApi()
    : createHttpApi({
        baseUrl: config.apiUrl,
        getToken: () => auth.getAccessToken(),
        // An expired or revoked session: sign out, which leads back to the sign-in page.
        onUnauthorized: () => void auth.signOut(),
      })
