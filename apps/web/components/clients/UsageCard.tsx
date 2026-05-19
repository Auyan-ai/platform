'use client'

import { useUsage } from '@/lib/api/hooks/usage'

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
    return <div className="h-36 animate-pulse rounded-xl bg-neutral-100" />
  }

  if (isError || !data) {
    return (
      <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
        No se pudo cargar el consumo.
      </div>
    )
  }

  const today = data.today
  const pct = Math.min(data.budget_used_pct, 100)
  const isWarning = pct >= 80
  const isCritical = pct >= 100

  const barColor = isCritical
    ? 'bg-red-500'
    : isWarning
      ? 'bg-amber-400'
      : 'bg-blue-500'

  return (
    <div className="rounded-xl border border-neutral-200 bg-white p-5 space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium uppercase tracking-wider text-neutral-400">
          Consumo hoy
        </p>
        <span className="text-xs text-neutral-400">
          presupuesto ${fmt(data.budget_usd_daily, 2)}/día
        </span>
      </div>

      {today ? (
        <>
          <div className="flex items-end gap-2">
            <p
              className={`text-3xl font-semibold ${
                isCritical ? 'text-red-600' : isWarning ? 'text-amber-600' : 'text-neutral-900'
              }`}
            >
              ${fmt(today.cost_usd)}
            </p>
            <p className="mb-1 text-sm text-neutral-400">USD</p>
          </div>

          {/* Barra de progreso */}
          <div>
            <div className="flex justify-between text-xs text-neutral-400 mb-1">
              <span>{pct.toFixed(1)}% del presupuesto</span>
              {isCritical && (
                <span className="font-medium text-red-600">Presupuesto agotado</span>
              )}
            </div>
            <div className="h-2 w-full rounded-full bg-neutral-100">
              <div
                className={`h-2 rounded-full transition-all ${barColor}`}
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-3 pt-1">
            <div>
              <p className="text-xs text-neutral-400">Tokens entrada</p>
              <p className="text-sm font-medium text-neutral-800">{fmtTokens(today.tokens_in)}</p>
            </div>
            <div>
              <p className="text-xs text-neutral-400">Tokens salida</p>
              <p className="text-sm font-medium text-neutral-800">{fmtTokens(today.tokens_out)}</p>
            </div>
            <div>
              <p className="text-xs text-neutral-400">Requests</p>
              <p className="text-sm font-medium text-neutral-800">{today.request_count}</p>
            </div>
          </div>
        </>
      ) : (
        <p className="text-sm text-neutral-400">Sin actividad hoy.</p>
      )}
    </div>
  )
}
