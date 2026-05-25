'use client'

import Link from 'next/link'
import { cn } from '@/lib/utils'
import {
  useSimulationScenarios,
  useRunSimulation,
  type SimulationScenario,
} from '@/lib/api/hooks/simulations'

interface ScenarioListProps {
  tenantId: string
}

function ScenarioRow({
  scenario,
  tenantId,
  onRun,
  isRunning,
}: {
  scenario: SimulationScenario
  tenantId: string
  onRun: (id: string) => void
  isRunning: boolean
}) {
  return (
    <div className="flex items-start gap-3 px-4 py-3 border-b border-neutral-100 last:border-0 hover:bg-neutral-50 transition-colors">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <Link
            href={`/tenants/${tenantId}/simulator/scenarios/${scenario.id}`}
            className="text-sm font-medium text-neutral-900 hover:underline truncate"
          >
            {scenario.name}
          </Link>
          {!scenario.is_active && (
            <span className="text-xs text-neutral-400 bg-neutral-100 rounded px-1.5 py-0.5">
              inactivo
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 text-xs text-neutral-400">
          <span className="font-mono">{scenario.aop_slug}</span>
          <span>·</span>
          <span className="truncate">{scenario.expected_outcome}</span>
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <span className="text-xs text-neutral-400">{scenario.max_turns}t máx</span>
        <button
          onClick={() => onRun(scenario.id)}
          disabled={isRunning}
          className={cn(
            'px-2.5 py-1 rounded-lg text-xs font-medium transition-colors',
            isRunning
              ? 'bg-neutral-100 text-neutral-400 cursor-not-allowed'
              : 'bg-neutral-900 text-white hover:bg-neutral-700',
          )}
        >
          {isRunning ? 'Corriendo…' : 'Run'}
        </button>
      </div>
    </div>
  )
}

export function ScenarioList({ tenantId }: ScenarioListProps) {
  const { data: scenarios, isLoading, error } = useSimulationScenarios(tenantId)
  const runMutation = useRunSimulation(tenantId)

  const handleRun = (scenarioId: string) => {
    runMutation.mutate(scenarioId)
  }

  if (isLoading) {
    return (
      <div className="divide-y divide-neutral-100">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="flex gap-3 px-4 py-3 animate-pulse">
            <div className="flex-1">
              <div className="h-4 w-48 bg-neutral-100 rounded mb-2" />
              <div className="h-3 w-64 bg-neutral-100 rounded" />
            </div>
            <div className="h-7 w-12 bg-neutral-100 rounded-lg" />
          </div>
        ))}
      </div>
    )
  }

  if (error) {
    return (
      <div className="px-4 py-6 text-sm text-red-500 text-center">
        Error cargando scenarios
      </div>
    )
  }

  if (!scenarios?.length) {
    return (
      <div className="px-4 py-10 text-sm text-neutral-400 text-center">
        Sin scenarios. Corre el seed script para cargarlos.
      </div>
    )
  }

  const grouped = scenarios.reduce<Record<string, SimulationScenario[]>>((acc, s) => {
    const key = s.aop_slug
    if (!acc[key]) acc[key] = []
    acc[key].push(s)
    return acc
  }, {})

  return (
    <div>
      {runMutation.isSuccess && (
        <div className="mx-4 mt-3 px-3 py-2 bg-emerald-50 border border-emerald-200 rounded-lg text-xs text-emerald-700">
          Run completado — abre el scenario para ver el resultado.
        </div>
      )}
      {runMutation.isError && (
        <div className="mx-4 mt-3 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-xs text-red-600">
          Error: {(runMutation.error as Error)?.message ?? 'desconocido'}
        </div>
      )}
      {Object.entries(grouped).map(([aopSlug, items]) => (
        <div key={aopSlug}>
          <div className="px-4 py-1.5 bg-neutral-50 border-b border-neutral-100">
            <span className="text-xs font-semibold text-neutral-500 uppercase tracking-wide font-mono">
              {aopSlug}
            </span>
            <span className="ml-2 text-xs text-neutral-400">{items.length} scenarios</span>
          </div>
          {items.map((s) => (
            <ScenarioRow
              key={s.id}
              scenario={s}
              tenantId={tenantId}
              onRun={handleRun}
              isRunning={runMutation.isPending && runMutation.variables === s.id}
            />
          ))}
        </div>
      ))}
    </div>
  )
}
