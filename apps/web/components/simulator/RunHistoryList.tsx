'use client'

import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Badge, type BadgeProps } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { RunDetail } from './RunDetail'
import type { SimulationRun, SimulationStatus } from '@/lib/api/hooks/simulations'

// ─── Status badge ─────────────────────────────────────────────────────────────

const STATUS_VARIANT: Record<SimulationStatus, BadgeProps['variant']> = {
  running: 'default',
  passed: 'success',
  partial: 'warning',
  failed: 'danger',
  errored: 'muted',
}

const STATUS_LABEL: Record<SimulationStatus, string> = {
  running: 'Corriendo…',
  passed: 'Pasado',
  partial: 'Parcial',
  failed: 'Fallido',
  errored: 'Error',
}

function formatDate(iso: string | null) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('es-ES', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// ─── RunHistoryList ───────────────────────────────────────────────────────────

interface RunHistoryListProps {
  runs: SimulationRun[]
  isLoading?: boolean
}

export function RunHistoryList({ runs, isLoading }: RunHistoryListProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null)

  if (isLoading) {
    return (
      <div className="divide-y divide-border-subtle">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="flex gap-3 px-4 py-3">
            <Skeleton className="h-5 w-16 rounded-xs" />
            <Skeleton className="h-4 w-32" />
          </div>
        ))}
      </div>
    )
  }

  if (!runs.length) {
    return (
      <div className="px-4 py-10 text-sm text-foreground-muted text-center">
        Sin runs aún. Lanza uno con el botón de arriba.
      </div>
    )
  }

  return (
    <div className="divide-y divide-border-subtle">
      {runs.map((run) => {
        const isOpen = expandedId === run.id
        const overall = run.judge_eval?.overall_score
        const assertionsSummary =
          run.assertions_total != null
            ? `${run.assertions_passed ?? 0}/${run.assertions_total} assertions`
            : null

        return (
          <div key={run.id}>
            <button
              onClick={() => setExpandedId(isOpen ? null : run.id)}
              className="w-full flex items-center gap-3 px-4 py-3 hover:bg-surface-muted transition-colors text-left"
            >
              <Badge variant={STATUS_VARIANT[run.status]}>{STATUS_LABEL[run.status]}</Badge>
              <span className="text-xs text-foreground-muted tabular-nums">
                {formatDate(run.started_at)}
              </span>
              {run.turns_count != null && (
                <span className="text-xs text-foreground-muted tabular-nums">
                  {run.turns_count} turnos
                </span>
              )}
              {overall != null && (
                <span
                  className={cn(
                    'text-xs font-semibold tabular-nums',
                    overall >= 7.5
                      ? 'text-success-foreground'
                      : overall >= 6
                        ? 'text-warning-foreground'
                        : 'text-danger-foreground',
                  )}
                >
                  {overall.toFixed(1)}/10
                </span>
              )}
              {assertionsSummary && (
                <span className="text-xs text-foreground-muted">{assertionsSummary}</span>
              )}
              {isOpen ? (
                <ChevronUp className="ml-auto size-4 text-foreground-subtle" />
              ) : (
                <ChevronDown className="ml-auto size-4 text-foreground-subtle" />
              )}
            </button>

            {isOpen && (
              <div className="border-t border-border-subtle bg-surface-muted">
                <RunDetail run={run} />
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
