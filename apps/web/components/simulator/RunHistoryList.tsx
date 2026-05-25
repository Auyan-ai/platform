'use client'

import { useState } from 'react'
import { cn } from '@/lib/utils'
import { RunDetail } from './RunDetail'
import type { SimulationRun, SimulationStatus } from '@/lib/api/hooks/simulations'

// ─── Status badge ─────────────────────────────────────────────────────────────

const STATUS_BADGE: Record<SimulationStatus, string> = {
  running: 'bg-blue-50 text-blue-600 border-blue-200',
  passed: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  partial: 'bg-amber-50 text-amber-700 border-amber-200',
  failed: 'bg-red-50 text-red-600 border-red-200',
  errored: 'bg-neutral-100 text-neutral-500 border-neutral-200',
}

const STATUS_LABEL: Record<SimulationStatus, string> = {
  running: 'Corriendo…',
  passed: 'Pasado',
  partial: 'Parcial',
  failed: 'Fallido',
  errored: 'Error',
}

function StatusBadge({ status }: { status: SimulationStatus }) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium',
        STATUS_BADGE[status],
      )}
    >
      {STATUS_LABEL[status]}
    </span>
  )
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
      <div className="divide-y divide-neutral-100">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="flex gap-3 px-4 py-3 animate-pulse">
            <div className="h-5 w-16 bg-neutral-100 rounded-full" />
            <div className="h-4 w-32 bg-neutral-100 rounded" />
          </div>
        ))}
      </div>
    )
  }

  if (!runs.length) {
    return (
      <div className="px-4 py-10 text-sm text-neutral-400 text-center">
        Sin runs aún. Lanza uno con el botón de arriba.
      </div>
    )
  }

  return (
    <div className="divide-y divide-neutral-100">
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
              className="w-full flex items-center gap-3 px-4 py-3 hover:bg-neutral-50 transition-colors text-left"
            >
              <StatusBadge status={run.status} />
              <span className="text-xs text-neutral-500 tabular-nums">
                {formatDate(run.started_at)}
              </span>
              {run.turns_count != null && (
                <span className="text-xs text-neutral-400">{run.turns_count} turnos</span>
              )}
              {overall != null && (
                <span
                  className={cn(
                    'text-xs font-semibold tabular-nums',
                    overall >= 7.5
                      ? 'text-emerald-600'
                      : overall >= 6
                        ? 'text-amber-600'
                        : 'text-red-500',
                  )}
                >
                  {overall.toFixed(1)}/10
                </span>
              )}
              {assertionsSummary && (
                <span className="text-xs text-neutral-400">{assertionsSummary}</span>
              )}
              <span className="ml-auto text-xs text-neutral-300">{isOpen ? '▲' : '▼'}</span>
            </button>

            {isOpen && (
              <div className="border-t border-neutral-100 bg-neutral-50">
                <RunDetail run={run} />
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
