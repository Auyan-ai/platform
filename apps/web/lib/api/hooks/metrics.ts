'use client'

import { useQuery } from '@tanstack/react-query'
import { getToken } from '@/lib/api/get-token'
import { queryKeys } from '@/lib/api/query-keys'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export interface TenantMetrics {
  total: number
  by_status: {
    open: number
    pending: number
    escalated: number
    resolved: number
    closed: number
  }
  resolution_rate: number
  escalation_rate: number
}

export function useMetrics(tenantId: string) {
  return useQuery({
    queryKey: queryKeys.tenants.metrics(tenantId),
    queryFn: async () => {
      const token = await getToken()
      const resp = await fetch(`${API_URL}/tenants/me/metrics`, {
        headers: {
          Authorization: `Bearer ${token}`,
          'X-Tenant-Id': tenantId,
        },
        cache: 'no-store',
      })
      if (!resp.ok) throw new Error(`metrics_error_${resp.status}`)
      return resp.json() as Promise<TenantMetrics>
    },
    staleTime: 30_000,
    refetchInterval: 60_000,
  })
}
