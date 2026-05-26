'use client'

import { useMetrics } from '@/lib/api/hooks/metrics'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'

interface MetricsCardsProps {
  tenantId: string
}

interface StatCardProps {
  label: string
  value: number | string
  sub?: string
  tone?: 'default' | 'accent' | 'danger' | 'success'
}

const TONE_CLASS: Record<NonNullable<StatCardProps['tone']>, string> = {
  default: 'text-foreground',
  accent: 'text-accent-foreground',
  danger: 'text-danger-foreground',
  success: 'text-success-foreground',
}

function StatCard({ label, value, sub, tone = 'default' }: StatCardProps) {
  return (
    <Card className="p-(--density-card-p)">
      <p className="text-xs font-medium uppercase tracking-wider text-foreground-muted">
        {label}
      </p>
      <p className={`mt-2 text-3xl font-semibold ${TONE_CLASS[tone]}`}>{value}</p>
      {sub && <p className="mt-1 text-xs text-foreground-muted">{sub}</p>}
    </Card>
  )
}

export function MetricsCards({ tenantId }: MetricsCardsProps) {
  const { data, isLoading, isError } = useMetrics(tenantId)

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {[...Array(4)].map((_, i) => (
          <Skeleton key={i} className="h-28" />
        ))}
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="rounded-md bg-danger-subtle px-4 py-3 text-sm text-danger-foreground">
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
        <StatCard label="Total tickets" value={data.total} sub="histórico" />
        <StatCard
          label="Activas"
          value={openAndPending}
          sub={`${data.by_status.open} abiertas · ${data.by_status.pending} pendientes`}
          tone="success"
        />
        <StatCard
          label="Escaladas"
          value={data.by_status.escalated}
          sub="requieren atención humana"
          tone={data.by_status.escalated > 0 ? 'danger' : 'default'}
        />
        <StatCard
          label="Resueltas + cerradas"
          value={data.by_status.resolved + data.by_status.closed}
          sub="histórico"
          tone="accent"
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <Card className="flex items-center gap-3 px-5 py-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-wider text-foreground-muted">
              Tasa de resolución
            </p>
            <p className="mt-1 text-2xl font-semibold text-accent-foreground">
              {resolutionPct}
            </p>
          </div>
        </Card>
        <Card className="flex items-center gap-3 px-5 py-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-wider text-foreground-muted">
              Tasa de escalación
            </p>
            <p
              className={`mt-1 text-2xl font-semibold ${
                data.escalation_rate > 0.1
                  ? 'text-danger-foreground'
                  : 'text-foreground'
              }`}
            >
              {escalationPct}
            </p>
          </div>
        </Card>
      </div>
    </div>
  )
}
