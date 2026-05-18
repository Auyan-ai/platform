'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getToken } from '@/lib/api/get-token'
import { queryKeys } from '@/lib/api/query-keys'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

// ─── Types ────────────────────────────────────────────────────────────────────

export type ProposalStatus = 'pending' | 'approved' | 'rejected' | 'applied'
export type ProposalType = 'aop_edit' | 'new_aop' | 'skill_request' | 'guardrail_addition'

export interface Proposal {
  id: string
  tenant_id: string
  run_id: string
  proposal_type: ProposalType
  aop_slug: string | null
  diff_markdown: string
  rationale: string
  evidence_conversations: string[]
  judge_model_used: string
  judge_confidence: number
  requires_eval_pass: boolean
  status: ProposalStatus
  reviewed_by: string | null
  reviewed_at: string | null
  review_comment: string | null
  applied_version: number | null
}

export interface ApproveProposalResult {
  proposal_id: string
  aop_id: string
  aop_version: number
  workspace: string
  redirect_to: string
}

export interface ProposalMetrics {
  total: number
  pending: number
  approved: number
  rejected: number
  applied: number
  acceptance_rate: number | null
  cost_usd_total: number
  cost_per_accepted_proposal: number | null
  sonnet_tokens_total: number
  opus_tokens_total: number
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

async function proposalFetch<T>(
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

// ─── Hooks ────────────────────────────────────────────────────────────────────

export function useProposals(
  tenantId: string,
  filters?: { status?: ProposalStatus; limit?: number; offset?: number },
) {
  return useQuery({
    queryKey: queryKeys.proposals.list(tenantId, filters),
    queryFn: async () => {
      const token = await getToken()
      const params = new URLSearchParams()
      if (filters?.status) params.set('proposal_status', filters.status)
      if (filters?.limit) params.set('limit', String(filters.limit))
      if (filters?.offset) params.set('offset', String(filters.offset))
      const qs = params.toString() ? `?${params.toString()}` : ''
      return proposalFetch<Proposal[]>(token, tenantId, `/proposals${qs}`)
    },
    staleTime: 15_000,
    refetchInterval: 30_000,
  })
}

export function useProposal(tenantId: string, proposalId: string) {
  return useQuery({
    queryKey: queryKeys.proposals.detail(tenantId, proposalId),
    queryFn: async () => {
      const token = await getToken()
      return proposalFetch<Proposal>(token, tenantId, `/proposals/${proposalId}`)
    },
    enabled: Boolean(proposalId),
  })
}

export function useProposalMetrics(tenantId: string) {
  return useQuery({
    queryKey: queryKeys.proposals.metrics(tenantId),
    queryFn: async () => {
      const token = await getToken()
      return proposalFetch<ProposalMetrics>(token, tenantId, '/proposals/metrics')
    },
    staleTime: 60_000,
  })
}

export function useApproveProposal(tenantId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (proposalId: string) => {
      const token = await getToken()
      return proposalFetch<ApproveProposalResult>(
        token,
        tenantId,
        `/proposals/${proposalId}/approve`,
        { method: 'POST' },
      )
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['proposals', tenantId] })
    },
  })
}

export function useRejectProposal(tenantId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      proposalId,
      comment,
    }: {
      proposalId: string
      comment?: string
    }) => {
      const token = await getToken()
      return proposalFetch<Proposal>(token, tenantId, `/proposals/${proposalId}/reject`, {
        method: 'POST',
        body: JSON.stringify({ comment: comment ?? null }),
      })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['proposals', tenantId] })
    },
  })
}
