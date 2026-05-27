'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getToken } from '@/lib/api/get-token'
import { queryKeys } from '@/lib/api/query-keys'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export interface TenantPlaybook {
  tenant_id: string
  brand_voice: string
  product_overview: string
  policies: string
  escalation_notes: string
  agent_instructions: string
  version: number
  last_edited_by: string | null
  updated_at: string | null
}

export interface TenantFacts {
  tenant_id: string
  data: Record<string, unknown>
  version: number
  last_edited_by: string | null
  updated_at: string | null
}

export type TenantPlaybookPayload = Pick<
  TenantPlaybook,
  'brand_voice' | 'product_overview' | 'policies' | 'escalation_notes' | 'agent_instructions'
>

async function tenantContextFetch<T>(
  token: string,
  tenantId: string,
  path: string,
  options?: RequestInit,
): Promise<T> {
  const resp = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      'X-Tenant-Id': tenantId,
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }))
    throw new Error(err.detail ?? `HTTP ${resp.status}`)
  }
  return resp.json() as Promise<T>
}

export function useTenantPlaybook(tenantId: string) {
  return useQuery({
    queryKey: queryKeys.tenants.playbook(tenantId),
    queryFn: async () => {
      const token = await getToken()
      return tenantContextFetch<TenantPlaybook>(token, tenantId, '/tenants/me/playbook')
    },
    staleTime: 30_000,
  })
}

export function useSaveTenantPlaybook(tenantId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: TenantPlaybookPayload) => {
      const token = await getToken()
      return tenantContextFetch<TenantPlaybook>(token, tenantId, '/tenants/me/playbook', {
        method: 'PUT',
        body: JSON.stringify(payload),
      })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.tenants.playbook(tenantId) })
    },
  })
}

export function useTenantFacts(tenantId: string) {
  return useQuery({
    queryKey: queryKeys.tenants.facts(tenantId),
    queryFn: async () => {
      const token = await getToken()
      return tenantContextFetch<TenantFacts>(token, tenantId, '/tenants/me/facts')
    },
    staleTime: 30_000,
  })
}

export function useSaveTenantFacts(tenantId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (data: Record<string, unknown>) => {
      const token = await getToken()
      return tenantContextFetch<TenantFacts>(token, tenantId, '/tenants/me/facts', {
        method: 'PUT',
        body: JSON.stringify({ data }),
      })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.tenants.facts(tenantId) })
    },
  })
}
