'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import { getToken } from '@/lib/api/get-token'
import { queryKeys } from '@/lib/api/query-keys'
import type { EscalationStatus } from '@auyan/shared'
import type { components } from '@auyan/shared/api-types'

type EscalationOut = components['schemas']['EscalationOut']
type EscalationsResponse = { escalations: EscalationOut[]; limit: number; offset: number }

export function useEscalations({
  tenantId,
  status,
  limit = 50,
  offset = 0,
}: {
  tenantId: string
  status?: EscalationStatus
  limit?: number
  offset?: number
}) {
  return useQuery({
    queryKey: queryKeys.escalations.list(tenantId, { status, limit, offset }),
    queryFn: async () => {
      const token = await getToken()
      const { data, error } = await apiClient(token, tenantId).GET('/escalations', {
        params: { query: { status, limit, offset } },
      })
      if (error) throw error
      return data as EscalationsResponse
    },
    refetchInterval: 5_000,
    refetchOnWindowFocus: true,
    staleTime: 0,
  })
}

export function useClaimMutation(tenantId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (escalationId: string) => {
      const token = await getToken()
      const { data, error } = await apiClient(token, tenantId).POST(
        '/escalations/{escalation_id}/claim',
        { params: { path: { escalation_id: escalationId } } },
      )
      if (error) throw error
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['escalations', tenantId] })
    },
  })
}

export function useResolveMutation(tenantId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (escalationId: string) => {
      const token = await getToken()
      const { data, error } = await apiClient(token, tenantId).POST(
        '/escalations/{escalation_id}/resolve',
        { params: { path: { escalation_id: escalationId } } },
      )
      if (error) throw error
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['escalations', tenantId] })
    },
  })
}
