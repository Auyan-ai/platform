'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { getToken } from '@/lib/api/get-token'
import { queryKeys } from '@/lib/api/query-keys'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export type ReasoningEvent = {
  id: string
  phase: 'supervisor' | 'decision' | 'response'
  event_type: 'check' | 'tool_call' | 'tool_result' | 'choice'
  label: string
  detail: Record<string, unknown> | null
  status: 'pending' | 'done' | 'error'
  seq: number
  created_at: string
}

export type ReasoningResponse = {
  conversation_id: string
  events: ReasoningEvent[]
}

async function fetchReasoningEvents(
  tenantId: string,
  conversationId: string,
): Promise<ReasoningResponse> {
  const token = await getToken()
  const res = await fetch(
    `${API_BASE}/conversations/${conversationId}/reasoning`,
    {
      headers: {
        Authorization: `Bearer ${token}`,
        'X-Tenant-Id': tenantId,
      },
    },
  )
  if (!res.ok) throw new Error(`reasoning_fetch_failed: ${res.status}`)
  return res.json()
}

/** Hook REST: carga historial de reasoning una vez (o cuando se invalida). */
export function useReasoningEvents(tenantId: string, conversationId: string) {
  return useQuery({
    queryKey: queryKeys.reasoning.events(tenantId, conversationId),
    queryFn: () => fetchReasoningEvents(tenantId, conversationId),
    staleTime: 5_000,
    refetchOnWindowFocus: false,
  })
}

/** Hook SSE: suscribe al stream y actualiza la query cache con eventos nuevos. */
export function useReasoningStream(
  tenantId: string,
  conversationId: string,
  enabled: boolean,
) {
  const queryClient = useQueryClient()
  const lastSeqRef = useRef(-1)

  useEffect(() => {
    if (!enabled) return

    let closed = false

    const connect = async () => {
      const token = await getToken()
      const url = new URL(
        `${API_BASE}/conversations/${conversationId}/reasoning/stream`,
      )
      // SSE con auth via fetch — EventSource nativo no soporta headers custom,
      // usamos fetch + ReadableStream
      const res = await fetch(url.toString(), {
        headers: {
          Authorization: `Bearer ${token}`,
          'X-Tenant-Id': tenantId,
          Accept: 'text/event-stream',
        },
      })

      if (!res.ok || !res.body) return
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (!closed) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          if (!line.startsWith('data:')) continue
          const raw = line.slice(5).trim()
          if (!raw || raw === '{}') continue
          try {
            const event: ReasoningEvent = JSON.parse(raw)
            if (event.seq <= lastSeqRef.current) continue
            lastSeqRef.current = event.seq

            queryClient.setQueryData<ReasoningResponse>(
              queryKeys.reasoning.events(tenantId, conversationId),
              (prev) => {
                const existing = prev?.events ?? []
                const alreadyHas = existing.some((e) => e.id === event.id)
                if (alreadyHas) return prev
                return {
                  conversation_id: conversationId,
                  events: [...existing, event],
                }
              },
            )
          } catch {
            // ignore malformed SSE frames
          }
        }
      }
    }

    connect().catch(() => {})

    return () => {
      closed = true
    }
  }, [tenantId, conversationId, enabled, queryClient])
}
