'use client'

import { getToken } from '@/lib/api/get-token'
import { queryKeys } from '@/lib/api/query-keys'
import type { ReturnsPolicy } from '@/lib/returns-policy'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { tenantContextFetch } from './tenant-context'

export interface ReturnsPolicyVersion {
  version: number
  edited_by_email: string | null
  created_at: string
}

export interface ReturnsPolicyResponse {
  tenant_id: string
  policy: ReturnsPolicy | null
  version: number | null
  updated_at: string | null
  edited_by_email: string | null
  history: ReturnsPolicyVersion[]
}

export interface SaveReturnsPolicyInput {
  policy: ReturnsPolicy
  expectedVersion: number | null
}

const PATH = '/tenants/me/returns-policy'

export function useReturnsPolicy(tenantId: string) {
  return useQuery({
    queryKey: queryKeys.tenants.returnsPolicy(tenantId),
    queryFn: async () => {
      const token = await getToken()
      return tenantContextFetch<ReturnsPolicyResponse>(token, tenantId, PATH)
    },
    staleTime: 30_000,
  })
}

export function useSaveReturnsPolicy(tenantId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ policy, expectedVersion }: SaveReturnsPolicyInput) => {
      const token = await getToken()
      return tenantContextFetch<ReturnsPolicyResponse>(token, tenantId, PATH, {
        method: 'PUT',
        body: JSON.stringify({ policy, expected_version: expectedVersion }),
      })
    },
    onSuccess: (saved) => {
      qc.setQueryData(queryKeys.tenants.returnsPolicy(tenantId), saved)
    },
  })
}
