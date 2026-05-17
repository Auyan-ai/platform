'use client'

import { useState } from 'react'
import { ChevronDown, ChevronRight, Loader2 } from 'lucide-react'
import { useReasoningEvents, useReasoningStream } from '@/lib/api/hooks/reasoning'
import { ReasoningPhase } from './ReasoningPhase'
import type { ReasoningEvent } from '@/lib/api/hooks/reasoning'

type Phase = ReasoningEvent['phase']
const PHASE_ORDER: Phase[] = ['supervisor', 'decision', 'response']

type Props = {
  tenantId: string
  conversationId: string
  /** Si true, el stream SSE está activo (conversación en proceso). */
  isActive?: boolean
  /** Si true, enmascara valores PII en tool call chips (vista tenant). */
  maskPII?: boolean
}

export function AgentReasoningPanel({
  tenantId,
  conversationId,
  isActive = false,
  maskPII = false,
}: Props) {
  const [open, setOpen] = useState(false)

  const { data, isLoading, isError } = useReasoningEvents(tenantId, conversationId)

  // SSE solo cuando el panel está abierto Y la conversación sigue activa
  useReasoningStream(tenantId, conversationId, open && isActive)

  const events = data?.events ?? []

  const byPhase = PHASE_ORDER.reduce<Record<Phase, ReasoningEvent[]>>(
    (acc, phase) => {
      acc[phase] = events.filter((e) => e.phase === phase)
      return acc
    },
    { supervisor: [], decision: [], response: [] },
  )

  const hasEvents = events.length > 0

  return (
    <div className="rounded-lg border border-border bg-card text-sm">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-4 py-2.5 text-left"
      >
        {open ? (
          <ChevronDown className="h-4 w-4 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-4 w-4 text-muted-foreground" />
        )}
        <span className="font-medium text-foreground">Agent reasoning</span>
        {isActive && isLoading && (
          <Loader2 className="ml-auto h-3.5 w-3.5 animate-spin text-muted-foreground" />
        )}
        {!isLoading && hasEvents && (
          <span className="ml-auto text-[11px] text-muted-foreground">
            {events.length} event{events.length !== 1 ? 's' : ''}
          </span>
        )}
      </button>

      {open && (
        <div className="border-t border-border px-4 py-3">
          {isLoading && (
            <p className="text-xs text-muted-foreground">Loading…</p>
          )}
          {isError && (
            <p className="text-xs text-destructive">
              No se pudo cargar el razonamiento del agente.
            </p>
          )}
          {!isLoading && !isError && !hasEvents && (
            <p className="text-xs text-muted-foreground">
              {isActive
                ? 'Esperando eventos del agente…'
                : 'Sin eventos de razonamiento registrados.'}
            </p>
          )}
          {!isLoading && hasEvents && (
            <div className="flex flex-col gap-3">
              {PHASE_ORDER.map((phase) => (
                <ReasoningPhase
                  key={phase}
                  phase={phase}
                  events={byPhase[phase]}
                  maskPII={maskPII}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
