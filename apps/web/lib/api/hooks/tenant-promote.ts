'use client'

import type { PlanTier } from '@/lib/api/hooks/tenant-create'
import { getToken } from '@/lib/api/get-token'
import { queryKeys } from '@/lib/api/query-keys'
import type { components } from '@auyan/shared/api-types'
import { useMutation, useQueryClient } from '@tanstack/react-query'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

type TenantResponse = components['schemas']['TenantResponse']

export type PromoteTenantInput = {
  admin_email: string
  admin_name: string
  plan_tier: PlanTier
  slug: string
}

export type PromoteTenantResult = {
  tenant: TenantResponse
  tenant_admin_user_id: string
  invite_sent: boolean
}

export function usePromoteTenant(tenantId: string) {
  const qc = useQueryClient()
  return useMutation<PromoteTenantResult, Error, PromoteTenantInput>({
    mutationFn: async (input) => {
      const token = await getToken()
      const resp = await fetch(`${API_URL}/tenants/${tenantId}/promote`, {
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
          if (typeof body.detail === 'string') detail = body.detail
        } catch {
          // ignore json parse error
        }
        throw new Error(detail)
      }
      return (await resp.json()) as PromoteTenantResult
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.tenants.adminList() })
      qc.invalidateQueries({ queryKey: queryKeys.tenants.adminReviewQueue() })
      qc.invalidateQueries({ queryKey: queryKeys.tenants.onboardingChecklist(tenantId) })
    },
  })
}
