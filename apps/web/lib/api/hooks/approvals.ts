'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getToken } from '@/lib/api/get-token'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export type ApprovalStatus = 'pending' | 'executing' | 'approved' | 'rejected' | 'failed'

export interface ApprovalOut {
  id: string
  conversation_id: string
  skill_slug: string
  skill_tier: string
  inputs_redacted: Record<string, unknown>
  // Datos reales que el operador necesita para revisar (ej. la dirección de envío).
  inputs_raw: Record<string, unknown>
  aop_slug: string
  aop_version: number
  status: ApprovalStatus
  reviewed_by: string | null
  reviewed_at: string | null
  review_comment: string | null
  created_at: string | null
}

export interface ApproveResult {
  approval_id: string
  // Estado de la aprobación tras aprobar: 'pending' si Shopify confirma que no se aplicó.
  approval_status: ApprovalStatus
  // success: aplicada. failed: no se aplicó (reintentable). refused: una regla la impide.
  // unknown: no se pudo comprobar si se aplicó.
  execution_status: 'success' | 'failed' | 'refused' | 'unknown'
  message_id: string | null
  output: Record<string, unknown>
  // Motivo con el que quedó escalada al equipo (ejecutada sin cerrar, rechazada por una
  // regla o con resultado desconocido). None si no hizo falta.
  team_followup?: string | null
}

async function apiFetch<T>(
  path: string,
  token: string,
  tenantId: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      'X-Tenant-Id': tenantId,
      ...(options?.headers as Record<string, string> | undefined),
    },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

export function useApprovals({
  tenantId,
  status = 'pending',
  limit = 50,
  offset = 0,
}: {
  tenantId: string
  status?: ApprovalStatus
  limit?: number
  offset?: number
}) {
  return useQuery({
    queryKey: ['approvals', tenantId, { status, limit, offset }],
    queryFn: async () => {
      const token = await getToken()
      const qs = new URLSearchParams({
        status,
        limit: String(limit),
        offset: String(offset),
      })
      return apiFetch<{ approvals: ApprovalOut[]; limit: number; offset: number }>(
        `/approvals?${qs}`,
        token,
        tenantId,
      )
    },
    refetchInterval: 10_000,
    refetchOnWindowFocus: true,
    staleTime: 0,
  })
}

export function useApproveMutation(tenantId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      approvalId,
      comment,
    }: {
      approvalId: string
      comment?: string | null
    }) => {
      const token = await getToken()
      return apiFetch<ApproveResult>(`/approvals/${approvalId}/approve`, token, tenantId, {
        method: 'POST',
        body: JSON.stringify({ comment: comment ?? null }),
      })
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['approvals', tenantId] }),
  })
}

export function useRejectMutation(tenantId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      approvalId,
      comment,
    }: {
      approvalId: string
      comment: string
    }) => {
      const token = await getToken()
      return apiFetch<unknown>(`/approvals/${approvalId}/reject`, token, tenantId, {
        method: 'POST',
        body: JSON.stringify({ comment }),
      })
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['approvals', tenantId] }),
  })
}
