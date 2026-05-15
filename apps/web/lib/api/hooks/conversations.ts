'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import { getToken } from '@/lib/api/get-token'
import { queryKeys } from '@/lib/api/query-keys'
import type { ConversationStatus } from '@auyan/shared'

export function useConversations({
  tenantId,
  status,
  limit = 50,
  offset = 0,
}: {
  tenantId: string
  status?: ConversationStatus
  limit?: number
  offset?: number
}) {
  return useQuery({
    queryKey: queryKeys.conversations.list(tenantId, { status, limit, offset }),
    queryFn: async () => {
      const token = await getToken()
      const { data, error } = await apiClient(token, tenantId).GET('/conversations', {
        params: {
          query: { status, limit, offset },
        },
      })
      if (error) throw error
      return data
    },
    refetchInterval: 5_000,
    refetchOnWindowFocus: true,
    staleTime: 0,
  })
}

export function useConversation(tenantId: string, conversationId: string) {
  return useQuery({
    queryKey: queryKeys.conversations.detail(tenantId, conversationId),
    queryFn: async () => {
      const token = await getToken()
      const { data, error } = await apiClient(token, tenantId).GET(
        '/conversations/{conversation_id}',
        { params: { path: { conversation_id: conversationId } } },
      )
      if (error) throw error
      return data
    },
    refetchInterval: 5_000,
    refetchOnWindowFocus: true,
    staleTime: 0,
  })
}

export function useReplyMutation(tenantId: string, conversationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (content: string) => {
      const token = await getToken()
      const { data, error } = await apiClient(token, tenantId).POST(
        '/conversations/{conversation_id}/reply',
        {
          params: { path: { conversation_id: conversationId } },
          body: { content },
        },
      )
      if (error) throw error
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.conversations.detail(tenantId, conversationId),
      })
      queryClient.invalidateQueries({ queryKey: ['conversations', tenantId] })
    },
  })
}

export function useEscalateMutation(tenantId: string, conversationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (reason: string) => {
      const token = await getToken()
      const { data, error } = await apiClient(token, tenantId).POST(
        '/conversations/{conversation_id}/escalate',
        {
          params: { path: { conversation_id: conversationId } },
          body: { reason },
        },
      )
      if (error) throw error
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.conversations.detail(tenantId, conversationId),
      })
      queryClient.invalidateQueries({ queryKey: ['conversations', tenantId] })
    },
  })
}

export function useCloseMutation(tenantId: string, conversationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const token = await getToken()
      const { data, error } = await apiClient(token, tenantId).POST(
        '/conversations/{conversation_id}/close',
        { params: { path: { conversation_id: conversationId } } },
      )
      if (error) throw error
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.conversations.detail(tenantId, conversationId),
      })
      queryClient.invalidateQueries({ queryKey: ['conversations', tenantId] })
    },
  })
}
