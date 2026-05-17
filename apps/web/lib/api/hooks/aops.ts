'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getToken } from '@/lib/api/get-token'
import { queryKeys } from '@/lib/api/query-keys'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

// ─── Types ────────────────────────────────────────────────────────────────────

export type AopWorkspace = 'production' | 'staging'

export interface AopSummary {
  id: string
  tenant_id: string
  slug: string
  workspace: AopWorkspace
  current_version: number
  is_active: boolean
  name: string
  description: string
}

export interface AopDetail extends AopSummary {
  yaml_frontmatter: Record<string, unknown>
  body_markdown: string
  raw_source: string
}

export interface AopValidateResult {
  valid: boolean
  system_prompt: string | null
  errors: string[]
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

async function aopFetch<T>(
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
  if (resp.status === 204) return undefined as T
  return resp.json() as Promise<T>
}

// ─── Hooks ────────────────────────────────────────────────────────────────────

export function useAops(tenantId: string, workspace: AopWorkspace = 'production') {
  return useQuery({
    queryKey: queryKeys.aops.list(tenantId, workspace),
    queryFn: async () => {
      const token = await getToken()
      return aopFetch<AopSummary[]>(
        token,
        tenantId,
        `/aops?workspace=${workspace}`,
      )
    },
    staleTime: 30_000,
  })
}

export function useAop(tenantId: string, aopId: string) {
  return useQuery({
    queryKey: queryKeys.aops.detail(tenantId, aopId),
    queryFn: async () => {
      const token = await getToken()
      return aopFetch<AopDetail>(token, tenantId, `/aops/${aopId}`)
    },
    enabled: Boolean(aopId),
  })
}

export function useCreateAop(tenantId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: { raw_source: string; workspace: AopWorkspace }) => {
      const token = await getToken()
      return aopFetch<AopDetail>(token, tenantId, '/aops', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
    },
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: queryKeys.aops.list(tenantId, data.workspace) })
    },
  })
}

export function useSaveAop(tenantId: string, aopId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: { raw_source: string }) => {
      const token = await getToken()
      return aopFetch<AopDetail>(token, tenantId, `/aops/${aopId}`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      })
    },
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: queryKeys.aops.detail(tenantId, aopId) })
      qc.invalidateQueries({ queryKey: queryKeys.aops.list(tenantId, data.workspace) })
    },
  })
}

export function useToggleAop(tenantId: string, workspace: AopWorkspace = 'production') {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ aopId, is_active }: { aopId: string; is_active: boolean }) => {
      const token = await getToken()
      return aopFetch<AopSummary>(token, tenantId, `/aops/${aopId}/toggle`, {
        method: 'PATCH',
        body: JSON.stringify({ is_active }),
      })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.aops.list(tenantId, workspace) })
    },
  })
}

export function useDeleteAop(tenantId: string, workspace: AopWorkspace = 'production') {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (aopId: string) => {
      const token = await getToken()
      return aopFetch<undefined>(token, tenantId, `/aops/${aopId}`, { method: 'DELETE' })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.aops.list(tenantId, workspace) })
    },
  })
}

export function useValidateAop(tenantId: string) {
  return useMutation({
    mutationFn: async (payload: { raw_source: string; workspace: AopWorkspace }) => {
      const token = await getToken()
      return aopFetch<AopValidateResult>(token, tenantId, '/aops/validate', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
    },
  })
}
