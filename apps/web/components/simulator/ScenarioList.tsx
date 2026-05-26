'use client'

import Link from 'next/link'
import {
  useSimulationScenarios,
  useRunSimulation,
  type SimulationScenario,
} from '@/lib/api/hooks/simulations'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

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
    <div className="flex items-start gap-3 px-4 py-3 border-b border-border-subtle last:border-0 hover:bg-surface-muted transition-colors">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <Link
            href={`/tenants/${tenantId}/simulator/scenarios/${scenario.id}`}
            className="text-sm font-medium text-foreground hover:underline truncate"
          >
            {scenario.name}
          </Link>
          {!scenario.is_active && (
            <Badge variant="muted" className="text-[10px]">
              inactivo
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2 text-xs text-foreground-muted">
          <span className="font-mono">{scenario.aop_slug}</span>
          <span>·</span>
          <span className="truncate">{scenario.expected_outcome}</span>
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <span className="text-xs text-foreground-muted tabular-nums">{scenario.max_turns}t máx</span>
        <Button
          size="sm"
          onClick={() => onRun(scenario.id)}
          disabled={isRunning}
          className="h-7 text-xs"
        >
          {isRunning ? 'Corriendo…' : 'Run'}
        </Button>
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
      <div className="divide-y divide-border-subtle">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="flex gap-3 px-4 py-3">
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-48" />
              <Skeleton className="h-3 w-64" />
            </div>
            <Skeleton className="h-7 w-12 rounded-sm" />
          </div>
        ))}
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-md bg-danger-subtle px-4 py-3 text-sm text-danger-foreground">
        Error cargando scenarios
      </div>
    )
  }

  if (!scenarios?.length) {
    return (
      <div className="px-4 py-10 text-sm text-foreground-muted text-center">
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
        <div className="mx-4 mt-3 rounded-md bg-success-subtle px-3 py-2 text-xs text-success-foreground">
          Run completado — abre el scenario para ver el resultado.
        </div>
      )}
      {runMutation.isError && (
        <div className="mx-4 mt-3 rounded-md bg-danger-subtle px-3 py-2 text-xs text-danger-foreground">
          Error: {(runMutation.error as Error)?.message ?? 'desconocido'}
        </div>
      )}
      {Object.entries(grouped).map(([aopSlug, items]) => (
        <div key={aopSlug}>
          <div className="px-4 py-1.5 bg-surface-muted border-b border-border-subtle">
            <span className="text-xs font-semibold text-foreground-muted uppercase tracking-wide font-mono">
              {aopSlug}
            </span>
            <span className="ml-2 text-xs text-foreground-muted">{items.length} scenarios</span>
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
