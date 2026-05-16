'use client'

import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import { getToken } from '@/lib/api/get-token'
import { queryKeys } from '@/lib/api/query-keys'
import type { components } from '@auyan/shared/api-types'

export type TenantMetrics = components['schemas']['TenantMetricsResponse']

export function useMetrics(tenantId: string) {
  return useQuery({
    queryKey: queryKeys.tenants.metrics(tenantId),
    queryFn: async () => {
      const token = await getToken()
      const { data, error } = await apiClient(token, tenantId).GET('/tenants/me/metrics')
      if (error) throw error
      return data
    },
    staleTime: 30_000,
    refetchInterval: 60_000,
  })
}
