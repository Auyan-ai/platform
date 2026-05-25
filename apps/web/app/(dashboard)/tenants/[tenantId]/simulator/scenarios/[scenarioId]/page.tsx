'use client'

import Link from 'next/link'
import { useParams } from 'next/navigation'
import { cn } from '@/lib/utils'
import { RunHistoryList } from '@/components/simulator/RunHistoryList'
import {
  useSimulationScenarios,
  useScenarioRuns,
  useRunSimulation,
} from '@/lib/api/hooks/simulations'

export default function ScenarioDetailPage() {
  const { tenantId, scenarioId } = useParams<{ tenantId: string; scenarioId: string }>()

  const { data: scenarios } = useSimulationScenarios(tenantId)
  const scenario = scenarios?.find((s) => s.id === scenarioId)

  const { data: runs, isLoading: runsLoading } = useScenarioRuns(tenantId, scenarioId)
  const runMutation = useRunSimulation(tenantId)

  const handleRun = () => {
    runMutation.mutate(scenarioId)
  }

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-4">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-neutral-500">
        <Link
          href={`/tenants/${tenantId}/simulator`}
          className="hover:text-neutral-900 transition-colors"
        >
          Simulator
        </Link>
        <span>/</span>
        <span className="text-neutral-900 font-medium truncate">
          {scenario?.name ?? scenarioId}
        </span>
      </div>

      {/* Scenario info */}
      {scenario && (
        <div className="rounded-xl border border-neutral-200 bg-white p-4 space-y-2">
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-1">
              <h1 className="text-base font-semibold text-neutral-900">{scenario.name}</h1>
              {scenario.description && (
                <p className="text-sm text-neutral-500">{scenario.description}</p>
              )}
            </div>
            <button
              onClick={handleRun}
              disabled={runMutation.isPending}
              className={cn(
                'shrink-0 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors',
                runMutation.isPending
                  ? 'bg-neutral-100 text-neutral-400 cursor-not-allowed'
                  : 'bg-neutral-900 text-white hover:bg-neutral-700',
              )}
            >
              {runMutation.isPending ? 'Corriendo…' : 'Run'}
            </button>
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-neutral-500">
            <span>
              <span className="font-medium">AOP:</span>{' '}
              <span className="font-mono">{scenario.aop_slug}</span>
            </span>
            <span>
              <span className="font-medium">Outcome esperado:</span> {scenario.expected_outcome}
            </span>
            <span>
              <span className="font-medium">Max turnos:</span> {scenario.max_turns}
            </span>
          </div>
        </div>
      )}

      {runMutation.isError && (
        <div className="px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-xs text-red-600">
          Error: {(runMutation.error as Error)?.message ?? 'desconocido'}
        </div>
      )}

      {/* Run history */}
      <div className="rounded-xl border border-neutral-200 bg-white overflow-hidden">
        <div className="px-4 py-3 border-b border-neutral-100">
          <span className="text-sm font-medium text-neutral-700">Historial de runs</span>
          {runs && (
            <span className="ml-2 text-xs text-neutral-400">{runs.length} total</span>
          )}
        </div>
        <RunHistoryList runs={runs ?? []} isLoading={runsLoading} />
      </div>
    </div>
  )
}
