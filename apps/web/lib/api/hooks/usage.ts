'use client'

import { useQuery } from '@tanstack/react-query'
import { getToken } from '@/lib/api/get-token'
import { queryKeys } from '@/lib/api/query-keys'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export interface TenantUsage {
  date: string
  tokens_in: number
  tokens_out: number
  cost_usd: number
  request_count: number
  budget_usd: number
  budget_used_pct: number
}

export function useUsage(tenantId: string) {
  return useQuery({
    queryKey: queryKeys.tenants.usage(tenantId),
    queryFn: async (): Promise<TenantUsage> => {
      const token = await getToken()
      const res = await fetch(`${API_URL}/tenants/me/usage`, {
        headers: {
          Authorization: `Bearer ${token}`,
          'X-Tenant-Id': tenantId,
        },
      })
      if (!res.ok) throw new Error('No se pudo cargar el consumo')
      return res.json()
    },
    staleTime: 60_000,
    refetchInterval: 120_000,
  })
}
