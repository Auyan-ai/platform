'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getToken } from '@/lib/api/get-token'
import { queryKeys } from '@/lib/api/query-keys'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export type ChatDecision = 'respond' | 'escalate' | 'error' | (string & {})

export interface ChatCustomerEntry {
  role: 'customer'
  content: string
  turn_number: number
}

export interface ChatAgentEntry {
  role: 'agent'
  content: string
  turn_number: number
  decision: ChatDecision
  escalation_reason: string | null
  skills: string[]
  trace_id: string | null
  cost_cents: number
  error: string | null
}

export type ChatEntry = ChatCustomerEntry | ChatAgentEntry

export interface ProbarAgenteChat {
  id: string
  tenant_id: string
  conversation_id: string | null
  turns: ChatEntry[]
  cost_cents: number
  started_at: string | null
}

export interface ChatTurnResult {
  decision: ChatDecision
  response_text: string
  escalation_reason: string | null
  skills: string[]
  trace_id: string | null
  cost_cents: number
  session_cost_cents: number
  error: string | null
}

async function chatFetch<T>(tenantId: string, path: string, options?: RequestInit): Promise<T> {
  const token = await getToken()
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
    const body = await resp.json().catch(() => ({}))
    const detail = body?.detail
    const message =
      typeof detail === 'string' ? detail : (detail?.message ?? resp.statusText)
    throw new Error(message || `HTTP ${resp.status}`)
  }
  return resp.json() as Promise<T>
}

export function useCreateChat(tenantId: string) {
  return useMutation({
    mutationFn: () =>
      chatFetch<ProbarAgenteChat>(tenantId, '/simulations/chats', { method: 'POST' }),
  })
}

export function useChat(tenantId: string, chatId: string | null) {
  return useQuery({
    queryKey: queryKeys.simulations.chat(tenantId, chatId ?? ''),
    queryFn: () => chatFetch<ProbarAgenteChat>(tenantId, `/simulations/chats/${chatId}`),
    enabled: Boolean(chatId),
    staleTime: Number.POSITIVE_INFINITY,
  })
}

export function useSendChatMessage(tenantId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ chatId, text }: { chatId: string; text: string }) =>
      chatFetch<ChatTurnResult>(tenantId, `/simulations/chats/${chatId}/messages`, {
        method: 'POST',
        body: JSON.stringify({ text }),
      }),
    onSettled: (_data, _error, { chatId }) =>
      qc.invalidateQueries({ queryKey: queryKeys.simulations.chat(tenantId, chatId) }),
  })
}
