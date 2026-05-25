'use client'

import { useState } from 'react'
import { useParams } from 'next/navigation'
import { cn } from '@/lib/utils'
import { ScenarioList } from '@/components/simulator/ScenarioList'
import {
  useSimulationScenarios,
  useRunBatch,
  useBatchRuns,
  type SimulationStatus,
} from '@/lib/api/hooks/simulations'

const STATUS_LABEL: Record<SimulationStatus, string> = {
  running: 'corriendo',
  passed: 'pasado',
  partial: 'parcial',
  failed: 'fallido',
  errored: 'error',
}

function BatchBanner({
  tenantId,
  batchId,
  onDismiss,
}: {
  tenantId: string
  batchId: string
  onDismiss: () => void
}) {
  const { data: runs } = useBatchRuns(tenantId, batchId)
  if (!runs) return null

  const done = runs.filter((r) => r.status !== 'running').length
  const total = runs.length
  const allDone = done === total

  const counts = runs.reduce<Partial<Record<SimulationStatus, number>>>(
    (acc, r) => ({ ...acc, [r.status]: (acc[r.status] ?? 0) + 1 }),
    {},
  )

  return (
    <div
      className={cn(
        'flex items-center justify-between px-4 py-2.5 border rounded-lg text-sm',
        allDone
          ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
          : 'bg-blue-50 border-blue-200 text-blue-800',
      )}
    >
      <div className="flex items-center gap-2">
        {!allDone && (
          <div className="w-3 h-3 rounded-full border-2 border-blue-400 border-t-transparent animate-spin" />
        )}
        <span>
          {allDone ? 'Batch completado' : 'Batch en progreso'} — {done}/{total}
        </span>
        <span className="text-xs opacity-70">
          {Object.entries(counts)
            .map(([s, n]) => `${n} ${STATUS_LABEL[s as SimulationStatus]}`)
            .join(' · ')}
        </span>
      </div>
      {allDone && (
        <button onClick={onDismiss} className="text-xs opacity-60 hover:opacity-100">
          Cerrar
        </button>
      )}
    </div>
  )
}

export default function SimulatorPage() {
  const { tenantId } = useParams<{ tenantId: string }>()
  const [batchId, setBatchId] = useState<string | null>(null)

  const { data: scenarios } = useSimulationScenarios(tenantId)
  const batchMutation = useRunBatch(tenantId)

  const handleRunAll = () => {
    if (!scenarios?.length) return
    const ids = scenarios.filter((s) => s.is_active).map((s) => s.id)
    batchMutation.mutate(ids, {
      onSuccess: (result) => setBatchId(result.batch_id),
    })
  }

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-neutral-900">Simulator</h1>
          <p className="text-sm text-neutral-500 mt-0.5">
            Corre scenarios contra el grafo real para detectar regresiones en los AOPs.
          </p>
        </div>
        <button
          onClick={handleRunAll}
          disabled={batchMutation.isPending || !scenarios?.length}
          className={cn(
            'px-3 py-1.5 rounded-lg text-sm font-medium transition-colors',
            batchMutation.isPending || !scenarios?.length
              ? 'bg-neutral-100 text-neutral-400 cursor-not-allowed'
              : 'bg-neutral-900 text-white hover:bg-neutral-700',
          )}
        >
          {batchMutation.isPending ? 'Lanzando…' : 'Run All'}
        </button>
      </div>

      {batchId && (
        <BatchBanner
          tenantId={tenantId}
          batchId={batchId}
          onDismiss={() => setBatchId(null)}
        />
      )}

      {batchMutation.isError && (
        <div className="px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-xs text-red-600">
          Error al lanzar batch: {(batchMutation.error as Error)?.message ?? 'desconocido'}
        </div>
      )}

      <div className="rounded-xl border border-neutral-200 bg-white overflow-hidden">
        <ScenarioList tenantId={tenantId} />
      </div>
    </div>
  )
}
