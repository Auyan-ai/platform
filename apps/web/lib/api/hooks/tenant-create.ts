'use client'

import { getToken } from '@/lib/api/get-token'
import { queryKeys } from '@/lib/api/query-keys'
import { useMutation, useQueryClient } from '@tanstack/react-query'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export type PlanTier = 'founding' | 'standard' | 'trial'

export type CreateTenantInput = {
  company_name: string
  slug: string
  plan_tier: PlanTier
  tenant_admin_email: string
  tenant_admin_name: string
}

export type CreateTenantResult = {
  tenant: {
    id: string
    slug: string
    name: string
    status: string
    agent_lifecycle_state: string
    plan_tier: PlanTier
  }
  tenant_admin_user_id: string
  invite_sent: boolean
}

export function useCreateTenant() {
  const qc = useQueryClient()
  return useMutation<CreateTenantResult, Error, CreateTenantInput>({
    mutationFn: async (input) => {
      const token = await getToken()
      const resp = await fetch(`${API_URL}/tenants`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(input),
      })
      if (!resp.ok) {
        let detail = `Error ${resp.status}`
        try {
          const body = (await resp.json()) as { detail?: string }
          if (body.detail) detail = body.detail
        } catch {
          // ignore json parse error
        }
        throw new Error(detail)
      }
      return (await resp.json()) as CreateTenantResult
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.tenants.adminList() })
      qc.invalidateQueries({ queryKey: queryKeys.tenants.adminReviewQueue() })
    },
  })
}
