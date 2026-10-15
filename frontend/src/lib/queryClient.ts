import { MutationCache, QueryClient } from '@tanstack/react-query'
import { ApiError, errorMessage } from '@/api/client'
import { translate, type MessageKey } from '@/i18n/store'
import { toast } from './toast'

interface MutationMeta extends Record<string, unknown> {
  /** Message key of the toast title on failure; set `silent` to handle the error locally instead. */
  errorTitle?: MessageKey
  silent?: boolean
}

declare module '@tanstack/react-query' {
  interface Register {
    mutationMeta: MutationMeta
  }
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      refetchOnWindowFocus: false,
      // Don't hammer a backend that is down or rejecting the request.
      retry: (failureCount, err) => {
        if (err instanceof ApiError && (err.status === 0 || (err.status >= 400 && err.status < 500))) return false
        return failureCount < 2
      },
    },
    mutations: { retry: false },
  },
  // Every failed mutation surfaces as a toast; queries render inline error states.
  mutationCache: new MutationCache({
    onError: (err, _variables, _ctx, mutation) => {
      const meta = mutation.meta
      if (meta?.silent) return
      toast.error(translate(meta?.errorTitle ?? 'err.generic'), errorMessage(err))
    },
  }),
})
