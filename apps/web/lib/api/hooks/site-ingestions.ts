'use client'

import { getToken } from '@/lib/api/get-token'
import { tenantContextFetch } from '@/lib/api/hooks/tenant-context'
import { queryKeys } from '@/lib/api/query-keys'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

export type IngestionStatus = 'queued' | 'fetching' | 'extracting' | 'ready' | 'failed'

export interface SourceStats {
  docs: number
  words: number
  requests: number
  rate_limited: number
  errors: number
  abandoned: string | null
  seconds: number
  discarded: Record<string, number>
}

export interface IngestionStats {
  origin?: string
  platform?: string | null
  seconds?: number
  robots?: string
  requests?: number
  rate_limited?: number
  docs?: number
  words?: number
  created?: number
  sources?: Record<string, SourceStats>
}

export interface SiteIngestion {
  id: string
  root_url: string
  platform: string | null
  status: IngestionStatus
  attempts: number
  failure_reason: string | null
  stats: IngestionStats
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface IngestionSubmission {
  id: string
  title: string
  source_url: string | null
  source_key: string | null
  status: 'pending_review' | 'approved' | 'rejected' | 'superseded'
  kind: string | null
  priority: 'normal' | 'low' | null
  source: string | null
  words: number | null
  review_note: string | null
}

export interface IngestionApproveResult {
  counts: { approved: number; rejected: number; skipped: number }
  failures: { submission_id: string; code: string; detail: string }[]
}

export const ACTIVE_INGESTION_STATUSES: IngestionStatus[] = ['queued', 'fetching', 'extracting']

const POLL_MS = 3_000

export function useLatestSiteIngestion(tenantId: string) {
  return useQuery({
    queryKey: queryKeys.tenants.siteIngestionLatest(tenantId),
    queryFn: async () => {
      const token = await getToken()
      return tenantContextFetch<SiteIngestion | null>(
        token,
        tenantId,
        '/tenants/me/site-ingestions/latest',
      )
    },
    refetchInterval: (query) =>
      query.state.data && ACTIVE_INGESTION_STATUSES.includes(query.state.data.status)
        ? POLL_MS
        : false,
  })
}

export function useStartSiteIngestion(tenantId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (url: string) => {
      const token = await getToken()
      return tenantContextFetch<{ id: string; status: IngestionStatus; root_url: string }>(
        token,
        tenantId,
        '/tenants/me/site-ingestions',
        { method: 'POST', body: JSON.stringify({ url }) },
      )
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.tenants.siteIngestionLatest(tenantId) })
    },
  })
}

export function useIngestionSubmissions(tenantId: string, ingestionId: string | null) {
  return useQuery({
    queryKey: queryKeys.tenants.siteIngestionSubmissions(tenantId, ingestionId ?? ''),
    enabled: ingestionId !== null,
    queryFn: async () => {
      const token = await getToken()
      return tenantContextFetch<IngestionSubmission[]>(
        token,
        tenantId,
        `/tenants/me/site-ingestions/${ingestionId}/submissions`,
      )
    },
  })
}

export function useApproveIngestionBatch(tenantId: string, ingestionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: { excludeSubmissionIds: string[]; reviewNote?: string }) => {
      const token = await getToken()
      return tenantContextFetch<IngestionApproveResult>(
        token,
        tenantId,
        `/tenants/me/site-ingestions/${ingestionId}/approve`,
        {
          method: 'POST',
          body: JSON.stringify({
            exclude_submission_ids: payload.excludeSubmissionIds,
            review_note: payload.reviewNote,
          }),
        },
      )
    },
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: queryKeys.tenants.siteIngestionSubmissions(tenantId, ingestionId),
      })
      qc.invalidateQueries({ queryKey: ['tenants', tenantId, 'kb-submissions'] })
      qc.invalidateQueries({ queryKey: queryKeys.tenants.kbDocuments(tenantId) })
    },
  })
}
