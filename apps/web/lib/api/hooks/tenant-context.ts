'use client'

import { getToken } from '@/lib/api/get-token'
import { queryKeys } from '@/lib/api/query-keys'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

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

export interface TenantOnboarding {
  tenant_id: string
  current_step: number
  completed_steps: number[]
  step_data: Record<string, unknown>
  submitted_at: string | null
  completed_at: string | null
  last_edited_by: string | null
  updated_at: string | null
}

export type KnowledgeSubmissionStatus = 'pending_review' | 'approved' | 'rejected'
export type KnowledgeSourceType = 'text' | 'url' | 'file'
export type WeeklyReportStatus = 'draft' | 'pending_review' | 'approved' | 'sent'

export interface TenantKnowledgeSubmission {
  id: string
  tenant_id: string
  title: string
  source_type: KnowledgeSourceType
  source_url: string | null
  original_filename: string | null
  content: string
  notes: string | null
  status: KnowledgeSubmissionStatus
  metadata: Record<string, unknown>
  submitted_by: string | null
  reviewed_by: string | null
  reviewed_at: string | null
  review_note: string | null
  processed_document_id: string | null
  created_at: string | null
  updated_at: string | null
}

export interface WeeklyReport {
  id: string
  tenant_id: string
  week_start: string
  week_end: string
  status: WeeklyReportStatus
  subject: string
  recipient_email: string | null
  metrics: Record<string, unknown>
  narrative: string
  created_by: string | null
  approved_by: string | null
  approved_at: string | null
  sent_by: string | null
  sent_at: string | null
  postmark_message_id: string | null
  send_error: string | null
  created_at: string | null
  updated_at: string | null
}

export type TenantPlaybookPayload = Pick<
  TenantPlaybook,
  'brand_voice' | 'product_overview' | 'policies' | 'escalation_notes' | 'agent_instructions'
>

export type TenantKnowledgeSubmissionPayload = Pick<
  TenantKnowledgeSubmission,
  'title' | 'source_type' | 'source_url' | 'original_filename' | 'content' | 'notes'
> & {
  metadata?: Record<string, unknown>
}

export interface WeeklyReportGeneratePayload {
  week_start: string
  week_end: string
  recipient_email?: string | null
}

export interface WeeklyReportUpdatePayload {
  reportId: string
  subject: string
  narrative: string
  recipient_email?: string | null
}

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

export function useTenantOnboarding(tenantId: string) {
  return useQuery({
    queryKey: queryKeys.tenants.onboarding(tenantId),
    queryFn: async () => {
      const token = await getToken()
      return tenantContextFetch<TenantOnboarding>(token, tenantId, '/tenants/me/onboarding')
    },
    staleTime: 30_000,
  })
}

export function useSaveTenantOnboarding(tenantId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (
      payload: Pick<TenantOnboarding, 'current_step' | 'completed_steps' | 'step_data'>,
    ) => {
      const token = await getToken()
      return tenantContextFetch<TenantOnboarding>(token, tenantId, '/tenants/me/onboarding', {
        method: 'PUT',
        body: JSON.stringify(payload),
      })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.tenants.onboarding(tenantId) })
    },
  })
}

export function useSubmitTenantOnboarding(tenantId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const token = await getToken()
      return tenantContextFetch<TenantOnboarding>(
        token,
        tenantId,
        '/tenants/me/onboarding/submit',
        { method: 'POST' },
      )
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.tenants.onboarding(tenantId) })
    },
  })
}

export function useTenantKnowledgeSubmissions(
  tenantId: string,
  status?: KnowledgeSubmissionStatus,
) {
  return useQuery({
    queryKey: queryKeys.tenants.kbSubmissions(tenantId, status),
    queryFn: async () => {
      const token = await getToken()
      const suffix = status ? `?status=${status}` : ''
      return tenantContextFetch<TenantKnowledgeSubmission[]>(
        token,
        tenantId,
        `/tenants/me/kb-submissions${suffix}`,
      )
    },
    staleTime: 20_000,
  })
}

export function useCreateTenantKnowledgeSubmission(tenantId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: TenantKnowledgeSubmissionPayload) => {
      const token = await getToken()
      return tenantContextFetch<TenantKnowledgeSubmission>(
        token,
        tenantId,
        '/tenants/me/kb-submissions',
        {
          method: 'POST',
          body: JSON.stringify(payload),
        },
      )
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.tenants.kbSubmissions(tenantId) })
      qc.invalidateQueries({
        queryKey: queryKeys.tenants.kbSubmissions(tenantId, 'pending_review'),
      })
    },
  })
}

export function useApproveTenantKnowledgeSubmission(tenantId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      submissionId,
      reviewNote,
    }: {
      submissionId: string
      reviewNote?: string
    }) => {
      const token = await getToken()
      return tenantContextFetch<TenantKnowledgeSubmission>(
        token,
        tenantId,
        `/tenants/me/kb-submissions/${submissionId}/approve`,
        {
          method: 'POST',
          body: JSON.stringify({ review_note: reviewNote ?? null }),
        },
      )
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.tenants.kbSubmissions(tenantId) })
      qc.invalidateQueries({
        queryKey: queryKeys.tenants.kbSubmissions(tenantId, 'pending_review'),
      })
    },
  })
}

export function useRejectTenantKnowledgeSubmission(tenantId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      submissionId,
      reviewNote,
    }: {
      submissionId: string
      reviewNote?: string
    }) => {
      const token = await getToken()
      return tenantContextFetch<TenantKnowledgeSubmission>(
        token,
        tenantId,
        `/tenants/me/kb-submissions/${submissionId}/reject`,
        {
          method: 'POST',
          body: JSON.stringify({ review_note: reviewNote ?? null }),
        },
      )
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.tenants.kbSubmissions(tenantId) })
      qc.invalidateQueries({
        queryKey: queryKeys.tenants.kbSubmissions(tenantId, 'pending_review'),
      })
    },
  })
}

export function useWeeklyReports(tenantId: string, status?: WeeklyReportStatus) {
  return useQuery({
    queryKey: queryKeys.tenants.weeklyReports(tenantId, status),
    queryFn: async () => {
      const token = await getToken()
      const suffix = status ? `?status=${status}` : ''
      return tenantContextFetch<WeeklyReport[]>(
        token,
        tenantId,
        `/tenants/me/weekly-reports${suffix}`,
      )
    },
    staleTime: 20_000,
  })
}

export function useGenerateWeeklyReport(tenantId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: WeeklyReportGeneratePayload) => {
      const token = await getToken()
      return tenantContextFetch<WeeklyReport>(
        token,
        tenantId,
        '/tenants/me/weekly-reports/generate',
        {
          method: 'POST',
          body: JSON.stringify(payload),
        },
      )
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.tenants.weeklyReports(tenantId) })
    },
  })
}

export function useUpdateWeeklyReport(tenantId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ reportId, ...payload }: WeeklyReportUpdatePayload) => {
      const token = await getToken()
      return tenantContextFetch<WeeklyReport>(
        token,
        tenantId,
        `/tenants/me/weekly-reports/${reportId}`,
        {
          method: 'PATCH',
          body: JSON.stringify(payload),
        },
      )
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.tenants.weeklyReports(tenantId) })
    },
  })
}

export function useSubmitWeeklyReport(tenantId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (reportId: string) => {
      const token = await getToken()
      return tenantContextFetch<WeeklyReport>(
        token,
        tenantId,
        `/tenants/me/weekly-reports/${reportId}/submit`,
        { method: 'POST' },
      )
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.tenants.weeklyReports(tenantId) })
    },
  })
}

export function useApproveWeeklyReport(tenantId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (reportId: string) => {
      const token = await getToken()
      return tenantContextFetch<WeeklyReport>(
        token,
        tenantId,
        `/tenants/me/weekly-reports/${reportId}/approve`,
        { method: 'POST' },
      )
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.tenants.weeklyReports(tenantId) })
    },
  })
}

export function useSendWeeklyReport(tenantId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (reportId: string) => {
      const token = await getToken()
      return tenantContextFetch<WeeklyReport>(
        token,
        tenantId,
        `/tenants/me/weekly-reports/${reportId}/send`,
        { method: 'POST' },
      )
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.tenants.weeklyReports(tenantId) })
      qc.invalidateQueries({ queryKey: queryKeys.tenants.weeklyReports(tenantId, 'sent') })
    },
  })
}
