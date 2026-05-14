'use client'

import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import { getToken } from '@/lib/api/get-token'
import { queryKeys } from '@/lib/api/query-keys'
import type { ConversationStatus } from '@auyan/shared'

export function useConversations({
  tenantId,
  status,
  limit = 50,
  offset = 0,
}: {
  tenantId: string
  status?: ConversationStatus
  limit?: number
  offset?: number
}) {
  return useQuery({
    queryKey: queryKeys.conversations.list(tenantId, { status, limit, offset }),
    queryFn: async () => {
      const token = await getToken()
      const { data, error } = await apiClient(token, tenantId).GET('/conversations', {
        params: {
          query: { status, limit, offset },
        },
      })
      if (error) throw error
      return data
    },
    refetchInterval: 5_000,
    refetchOnWindowFocus: true,
    staleTime: 0,
  })
}
