'use client'

import { useMetrics } from '@/lib/api/hooks/metrics'

interface MetricsCardsProps {
  tenantId: string
}

interface StatCardProps {
  label: string
  value: number | string
  sub?: string
  accent?: string
}

function StatCard({ label, value, sub, accent = 'text-neutral-900' }: StatCardProps) {
  return (
    <div className="rounded-xl border border-neutral-200 bg-white p-5">
      <p className="text-xs font-medium uppercase tracking-wider text-neutral-400">{label}</p>
      <p className={`mt-2 text-3xl font-semibold ${accent}`}>{value}</p>
      {sub && <p className="mt-1 text-xs text-neutral-400">{sub}</p>}
    </div>
  )
}

export function MetricsCards({ tenantId }: MetricsCardsProps) {
  const { data, isLoading, isError } = useMetrics(tenantId)

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-28 animate-pulse rounded-xl bg-neutral-100" />
        ))}
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
        No se pudieron cargar las métricas.
      </div>
    )
  }

  const openAndPending = data.by_status.open + data.by_status.pending
  const resolutionPct = `${(data.resolution_rate * 100).toFixed(1)}%`
  const escalationPct = `${(data.escalation_rate * 100).toFixed(1)}%`

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          label="Total tickets"
          value={data.total}
          sub="histórico"
        />
        <StatCard
          label="Activas"
          value={openAndPending}
          sub={`${data.by_status.open} abiertas · ${data.by_status.pending} pendientes`}
          accent="text-green-700"
        />
        <StatCard
          label="Escaladas"
          value={data.by_status.escalated}
          sub="requieren atención humana"
          accent={data.by_status.escalated > 0 ? 'text-red-600' : 'text-neutral-900'}
        />
        <StatCard
          label="Resueltas + cerradas"
          value={data.by_status.resolved + data.by_status.closed}
          sub="histórico"
          accent="text-blue-700"
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="flex items-center gap-3 rounded-xl border border-neutral-200 bg-white px-5 py-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-wider text-neutral-400">
              Tasa de resolución
            </p>
            <p className="mt-1 text-2xl font-semibold text-blue-700">{resolutionPct}</p>
          </div>
        </div>
        <div className="flex items-center gap-3 rounded-xl border border-neutral-200 bg-white px-5 py-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-wider text-neutral-400">
              Tasa de escalación
            </p>
            <p className={`mt-1 text-2xl font-semibold ${data.escalation_rate > 0.1 ? 'text-red-600' : 'text-neutral-900'}`}>
              {escalationPct}
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
