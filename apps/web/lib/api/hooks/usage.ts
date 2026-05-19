'use client'

import { useQuery } from '@tanstack/react-query'
import { getToken } from '@/lib/api/get-token'
import { queryKeys } from '@/lib/api/query-keys'

export interface DailyUsage {
  date: string
  tokens_in: number
  tokens_out: number
  cost_usd: number
  request_count: number
}

export interface TenantUsage {
  today: DailyUsage | null
  budget_usd_daily: number
  budget_used_pct: number
  days: number
  history: DailyUsage[]
}

export function useUsage(tenantId: string, days = 7) {
  return useQuery({
    queryKey: queryKeys.tenants.usage(tenantId, days),
    queryFn: async (): Promise<TenantUsage> => {
      const token = await getToken()
      const apiBase = process.env.NEXT_PUBLIC_API_URL ?? ''
      const res = await fetch(
        `${apiBase}/tenants/me/usage?days=${days}`,
        {
          headers: {
            Authorization: `Bearer ${token}`,
            'X-Tenant-Id': tenantId,
          },
        }
      )
      if (!res.ok) throw new Error(`usage fetch failed: ${res.status}`)
      return res.json()
    },
    staleTime: 60_000,
    refetchInterval: 120_000,
  })
}
