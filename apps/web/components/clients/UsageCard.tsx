'use client'

import { useUsage } from '@/lib/api/hooks/usage'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'

interface UsageCardProps {
  tenantId: string
}

function fmt(n: number, decimals = 4) {
  return n.toFixed(decimals)
}

function fmtTokens(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

export function UsageCard({ tenantId }: UsageCardProps) {
  const { data, isLoading, isError } = useUsage(tenantId)

  if (isLoading) {
    return <Skeleton className="h-36" />
  }

  if (isError || !data) {
    return (
      <div className="rounded-md bg-danger-subtle px-4 py-3 text-sm text-danger-foreground">
        No se pudo cargar el consumo.
      </div>
    )
  }

  const today = data.today
  const pct = Math.min(data.budget_used_pct, 100)
  const isWarning = pct >= 80
  const isCritical = pct >= 100

  const barColorClass = isCritical
    ? 'bg-danger'
    : isWarning
      ? 'bg-warning'
      : 'bg-accent'

  const numberColorClass = isCritical
    ? 'text-danger-foreground'
    : isWarning
      ? 'text-warning-foreground'
      : 'text-foreground'

  return (
    <Card className="p-(--density-card-p) space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium uppercase tracking-wider text-foreground-muted">
          Consumo hoy
        </p>
        <span className="text-xs text-foreground-muted tabular-nums">
          presupuesto ${fmt(data.budget_usd_daily, 2)}/día
        </span>
      </div>

      {today ? (
        <>
          <div className="flex items-end gap-2">
            <p className={`text-3xl font-semibold tabular-nums ${numberColorClass}`}>
              ${fmt(today.cost_usd)}
            </p>
            <p className="mb-1 text-sm text-foreground-muted">USD</p>
          </div>

          {/* Barra de progreso */}
          <div>
            <div className="flex justify-between text-xs text-foreground-muted mb-1">
              <span className="tabular-nums">{pct.toFixed(1)}% del presupuesto</span>
              {isCritical && (
                <span className="font-medium text-danger-foreground">
                  Presupuesto agotado
                </span>
              )}
            </div>
            <div className="h-2 w-full rounded-full bg-surface-muted overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${barColorClass}`}
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-3 pt-1">
            <div>
              <p className="text-xs text-foreground-muted">Tokens entrada</p>
              <p className="text-sm font-medium text-foreground-body tabular-nums">
                {fmtTokens(today.tokens_in)}
              </p>
            </div>
            <div>
              <p className="text-xs text-foreground-muted">Tokens salida</p>
              <p className="text-sm font-medium text-foreground-body tabular-nums">
                {fmtTokens(today.tokens_out)}
              </p>
            </div>
            <div>
              <p className="text-xs text-foreground-muted">Requests</p>
              <p className="text-sm font-medium text-foreground-body tabular-nums">
                {today.request_count}
              </p>
            </div>
          </div>
        </>
      ) : (
        <p className="text-sm text-foreground-muted">Sin actividad hoy.</p>
      )}
    </Card>
  )
}
