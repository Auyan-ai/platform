'use client'

import { getToken } from '@/lib/api/get-token'
import { queryKeys } from '@/lib/api/query-keys'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

// NEXT_PUBLIC_API_URL se inlinea en build time (ver apps/web/Dockerfile).
// Si llegara vacía al cliente, fetches harían "Load failed" silencioso por
// mixed-content (http://localhost:8000 desde una página https). Mejor fallar
// explícitamente que dejar al cliente con un error inútil.
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? ''

if (typeof window !== 'undefined' && !API_URL) {
  console.error(
    '[auyan] NEXT_PUBLIC_API_URL no se inyectó en el bundle. ' +
      'El frontend no podrá llamar al API. ' +
      'Revisa el Dockerfile (ARG/ENV) y las Variables de Railway.',
  )
}

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

export type KnowledgeSubmissionStatus = 'pending_review' | 'approved' | 'rejected' | 'superseded'
export type KnowledgeSourceType = 'text' | 'url' | 'file'
export type WeeklyReportStatus = 'draft' | 'pending_review' | 'approved' | 'sent'
export type OutboundEmailJobStatus = 'queued' | 'sending' | 'sent' | 'failed' | 'canceled'

export interface TenantKnowledgeSubmission {
  id: string
  tenant_id: string
  title: string
  source_type: KnowledgeSourceType
  source_url: string | null
  source_key: string | null
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

export interface KnowledgeDocument {
  id: string
  title: string
  source: string | null
  source_key: string | null
  created_at: string
  chunk_count: number
}

export interface OnboardingChecklist {
  onboarding_submitted: boolean
  has_commerce_integration: boolean
  has_helpdesk_integration: boolean
  has_knowledge: boolean
}

export interface OnboardingChecklistResponse extends OnboardingChecklist {
  complete: boolean
  agent_lifecycle_state: string
}

export interface TenantIntegrationStatus {
  kind: 'helpdesk' | 'commerce' | 'channel' | 'llm'
  provider: string
  is_active: boolean
  is_primary_for_kind: boolean
  config: Record<string, unknown>
  enabled_at: string | null
}

export interface TenantIntegrationsOverview {
  integrations: TenantIntegrationStatus[]
  checklist: OnboardingChecklistResponse
}

export interface ConnectShopifyPayload {
  domain: string
  client_id: string
  client_secret: string
}

export interface ConnectChatwootPayload {
  base_url: string
  account_id: string
  api_access_token: string
  escalation_team_id?: string | null
}

export interface ConnectIntegrationResponse {
  integration: TenantIntegrationStatus
  checklist: OnboardingChecklistResponse
  webhook_registered: boolean | null
}

export interface TenantInsightTimelinePoint {
  date: string
  conversations: number
}

export interface TenantInsightBreakdownItem {
  label: string
  count: number
}

export interface TenantInsights {
  days: number
  timeline: TenantInsightTimelinePoint[]
  top_intents: TenantInsightBreakdownItem[]
  by_channel: TenantInsightBreakdownItem[]
  by_status: TenantInsightBreakdownItem[]
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

export interface OutboundEmailTemplate {
  id: string
  tenant_id: string
  key: string
  name: string
  subject_template: string
  text_body_template: string
  html_body_template: string | null
  variables: string[]
  is_active: boolean
  version: number
  created_by: string | null
  updated_by: string | null
  created_at: string | null
  updated_at: string | null
}

export interface OutboundEmailJob {
  id: string
  tenant_id: string
  template_id: string | null
  recipient_email: string
  subject: string
  text_body: string
  html_body: string | null
  tag: string | null
  payload: Record<string, unknown>
  status: OutboundEmailJobStatus
  attempts: number
  max_attempts: number
  next_attempt_at: string | null
  last_attempt_at: string | null
  sent_at: string | null
  postmark_message_id: string | null
  error: string | null
  requested_by: string | null
  idempotency_key: string | null
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

export type OutboundEmailTemplatePayload = Pick<
  OutboundEmailTemplate,
  | 'key'
  | 'name'
  | 'subject_template'
  | 'text_body_template'
  | 'html_body_template'
  | 'variables'
  | 'is_active'
>

export interface OutboundEmailTemplateUpdatePayload
  extends Omit<OutboundEmailTemplatePayload, 'key'> {
  templateId: string
}

export type OutboundEmailJobPayload = Pick<
  OutboundEmailJob,
  'recipient_email' | 'subject' | 'text_body' | 'html_body' | 'tag' | 'payload'
> & {
  template_id?: string | null
  idempotency_key?: string | null
  max_attempts?: number
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly body: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export async function tenantContextFetch<T>(
  token: string,
  tenantId: string,
  path: string,
  options?: RequestInit,
): Promise<T> {
  if (!API_URL) {
    throw new Error(
      'NEXT_PUBLIC_API_URL no está configurada. Revisa el deploy de Railway.',
    )
  }
  const url = `${API_URL}${path}`
  let resp: Response
  try {
    resp = await fetch(url, {
      ...options,
      headers: {
        Authorization: `Bearer ${token}`,
        'X-Tenant-Id': tenantId,
        'Content-Type': 'application/json',
        ...options?.headers,
      },
    })
  } catch (err) {
    // fetch throw = network / CORS / mixed-content. Mensaje claro para debugging.
    console.error('[auyan] fetch error', { url, method: options?.method ?? 'GET', err })
    throw new Error(
      `No se pudo contactar el API (${options?.method ?? 'GET'} ${path}). Revisa DevTools → Network para el detalle.`,
    )
  }
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }))
    throw new ApiError(
      typeof err.detail === 'string' ? err.detail : `HTTP ${resp.status}`,
      resp.status,
      err,
    )
  }
  if (resp.status === 204) return undefined as T
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
    // staleTime 0: necesitamos que al volver a abrir la pestaña veamos el current_step
    // real, no la versión cacheada — el portal usa esto para resume-where-left-off.
    staleTime: 0,
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
      // El submit reevalúa lifecycle server-side. Invalidamos el checklist para
      // que el OnboardingPortal vea el lifecycle actualizado y redirija al
      // dashboard si pasó a 'building'.
      qc.invalidateQueries({ queryKey: queryKeys.tenants.onboardingChecklist(tenantId) })
    },
  })
}

export function useTenantOnboardingChecklist(tenantId: string) {
  return useQuery({
    queryKey: queryKeys.tenants.onboardingChecklist(tenantId),
    queryFn: async () => {
      const token = await getToken()
      return tenantContextFetch<OnboardingChecklistResponse>(
        token,
        tenantId,
        '/tenants/me/onboarding/checklist',
      )
    },
    staleTime: 10_000,
  })
}

export function useTenantIntegrations(tenantId: string) {
  return useQuery({
    queryKey: queryKeys.tenants.integrations(tenantId),
    queryFn: async () => {
      const token = await getToken()
      return tenantContextFetch<TenantIntegrationsOverview>(
        token,
        tenantId,
        '/tenants/me/integrations',
      )
    },
    staleTime: 10_000,
  })
}

export function useConnectShopify(tenantId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: ConnectShopifyPayload) => {
      const token = await getToken()
      return tenantContextFetch<ConnectIntegrationResponse>(
        token,
        tenantId,
        '/tenants/me/integrations/shopify',
        { method: 'POST', body: JSON.stringify(payload) },
      )
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.tenants.integrations(tenantId) })
      qc.invalidateQueries({ queryKey: queryKeys.tenants.onboardingChecklist(tenantId) })
    },
  })
}

/**
 * Devuelve la URL de autorización OAuth para el proveedor indicado.
 * El endpoint `/oauth/{provider}/authorize?format=json` requiere Bearer auth,
 * por eso lo hacemos vía fetch — no como `<a href>`. El frontend hace
 * window.location.href con el resultado.
 */
export async function fetchOAuthAuthorizeUrl(
  provider: 'gorgias' | 'zendesk',
  params: Record<string, string>,
): Promise<string> {
  const token = await getToken()
  const query = new URLSearchParams({ ...params, format: 'json' }).toString()
  const resp = await fetch(`${API_URL}/oauth/${provider}/authorize?${query}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }))
    throw new Error(err.detail ?? `HTTP ${resp.status}`)
  }
  const body = (await resp.json()) as { authorize_url: string }
  return body.authorize_url
}

export function useConnectChatwoot(tenantId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: ConnectChatwootPayload) => {
      const token = await getToken()
      return tenantContextFetch<ConnectIntegrationResponse>(
        token,
        tenantId,
        '/tenants/me/integrations/chatwoot',
        { method: 'POST', body: JSON.stringify(payload) },
      )
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.tenants.integrations(tenantId) })
      qc.invalidateQueries({ queryKey: queryKeys.tenants.onboardingChecklist(tenantId) })
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

export function useKnowledgeDocuments(tenantId: string) {
  return useQuery({
    queryKey: queryKeys.tenants.kbDocuments(tenantId),
    queryFn: async () => {
      const token = await getToken()
      return tenantContextFetch<KnowledgeDocument[]>(token, tenantId, '/tenants/me/kb-documents')
    },
    staleTime: 20_000,
  })
}

export function useDeleteKnowledgeDocument(tenantId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (documentId: string) => {
      const token = await getToken()
      return tenantContextFetch<void>(token, tenantId, `/tenants/me/kb-documents/${documentId}`, {
        method: 'DELETE',
      })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.tenants.kbDocuments(tenantId) })
    },
  })
}

export function useTenantInsights(tenantId: string, days = 14) {
  return useQuery({
    queryKey: queryKeys.tenants.insights(tenantId, days),
    queryFn: async () => {
      const token = await getToken()
      return tenantContextFetch<TenantInsights>(
        token,
        tenantId,
        `/tenants/me/insights?days=${days}`,
      )
    },
    staleTime: 30_000,
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
      // El backend reevalúa lifecycle al crear la KB — refresca el checklist.
      qc.invalidateQueries({ queryKey: queryKeys.tenants.onboardingChecklist(tenantId) })
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
      qc.invalidateQueries({ queryKey: queryKeys.tenants.kbDocuments(tenantId) })
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

export function useOutboundEmailTemplates(tenantId: string) {
  return useQuery({
    queryKey: queryKeys.tenants.outboundEmailTemplates(tenantId),
    queryFn: async () => {
      const token = await getToken()
      return tenantContextFetch<OutboundEmailTemplate[]>(
        token,
        tenantId,
        '/tenants/me/outbound-email/templates?include_inactive=true',
      )
    },
    staleTime: 20_000,
  })
}

export function useCreateOutboundEmailTemplate(tenantId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: OutboundEmailTemplatePayload) => {
      const token = await getToken()
      return tenantContextFetch<OutboundEmailTemplate>(
        token,
        tenantId,
        '/tenants/me/outbound-email/templates',
        {
          method: 'POST',
          body: JSON.stringify(payload),
        },
      )
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.tenants.outboundEmailTemplates(tenantId) })
    },
  })
}

export function useUpdateOutboundEmailTemplate(tenantId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ templateId, ...payload }: OutboundEmailTemplateUpdatePayload) => {
      const token = await getToken()
      return tenantContextFetch<OutboundEmailTemplate>(
        token,
        tenantId,
        `/tenants/me/outbound-email/templates/${templateId}`,
        {
          method: 'PATCH',
          body: JSON.stringify(payload),
        },
      )
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.tenants.outboundEmailTemplates(tenantId) })
    },
  })
}

export function useOutboundEmailJobs(tenantId: string, status?: OutboundEmailJobStatus) {
  return useQuery({
    queryKey: queryKeys.tenants.outboundEmailJobs(tenantId, status),
    queryFn: async () => {
      const token = await getToken()
      const suffix = status ? `?status=${status}&limit=50` : '?limit=50'
      return tenantContextFetch<OutboundEmailJob[]>(
        token,
        tenantId,
        `/tenants/me/outbound-email/jobs${suffix}`,
      )
    },
    staleTime: 10_000,
  })
}

export function useEnqueueOutboundEmailJob(tenantId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: OutboundEmailJobPayload) => {
      const token = await getToken()
      return tenantContextFetch<OutboundEmailJob>(
        token,
        tenantId,
        '/tenants/me/outbound-email/jobs',
        {
          method: 'POST',
          body: JSON.stringify(payload),
        },
      )
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.tenants.outboundEmailJobs(tenantId) })
      qc.invalidateQueries({ queryKey: queryKeys.tenants.outboundEmailJobs(tenantId, 'queued') })
      qc.invalidateQueries({ queryKey: queryKeys.tenants.outboundEmailJobs(tenantId, 'failed') })
    },
  })
}
