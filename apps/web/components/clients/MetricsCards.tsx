'use client'

import { useMetrics } from '@/lib/api/hooks/metrics'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import { ArrowDownRight, ArrowUpRight, BarChart3, CircleAlert, Inbox } from 'lucide-react'

interface MetricsCardsProps {
  tenantId: string
}

const SKELETON_KEYS = ['metrics-a', 'metrics-b', 'metrics-c', 'metrics-d']

function MiniCard({
  label,
  value,
  sub,
  icon: Icon,
}: {
  label: string
  value: number | string
  sub: string
  icon: typeof Inbox
}) {
  return (
    <Card className="p-(--density-card-p)">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-foreground">{label}</p>
          <p className="mt-2 text-2xl font-semibold tabular-nums text-foreground">{value}</p>
        </div>
        <div className="grid size-8 place-items-center rounded-md bg-surface-muted text-foreground-muted">
          <Icon className="size-4" />
        </div>
      </div>
      <p className="mt-4 border-t border-border-subtle pt-3 text-xs text-foreground-muted">
        {sub}
      </p>
    </Card>
  )
}

function SupportLineChart() {
  const points = '0,78 22,64 44,69 66,48 88,54 110,39 132,45 154,34 176,28 198,42 220,31 242,36 264,24 286,30 308,18 330,26 352,14'
  return (
    <div className="relative mt-8 h-44 overflow-hidden rounded-sm">
      <svg viewBox="0 0 352 120" className="absolute inset-0 h-full w-full" role="img" aria-label="Actividad de soporte">
        <defs>
          <linearGradient id="supportFill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="var(--color-accent)" stopOpacity="0.34" />
            <stop offset="100%" stopColor="var(--color-accent)" stopOpacity="0.04" />
          </linearGradient>
        </defs>
        <path d={`M ${points} L 352,120 L 0,120 Z`} fill="url(#supportFill)" />
        <polyline
          points={points}
          fill="none"
          stroke="var(--color-accent-foreground)"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="2.2"
        />
      </svg>
      <div className="absolute bottom-0 left-0 right-0 flex justify-between px-2 text-xs text-foreground-subtle">
        <span>Hace 30d</span>
        <span>Hace 15d</span>
        <span>Hoy</span>
      </div>
    </div>
  )
}

export function MetricsCards({ tenantId }: MetricsCardsProps) {
  const { data, isLoading, isError } = useMetrics(tenantId)

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {SKELETON_KEYS.map((key) => (
          <Skeleton key={key} className="h-28" />
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

  const active = data.by_status.open + data.by_status.pending
  const resolutionPct = `${(data.resolution_rate * 100).toFixed(1)}%`
  const escalationPct = `${(data.escalation_rate * 100).toFixed(1)}%`
  const handled = data.by_status.resolved + data.by_status.closed

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-[1.08fr_0.92fr]">
        <Card className="overflow-hidden p-(--density-card-p)">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <p className="text-sm font-medium text-foreground">Resolución IA</p>
                <Badge variant="default">Últimos 30 días</Badge>
              </div>
              <p className="mt-3 text-4xl font-semibold tabular-nums text-foreground">
                {handled}
              </p>
              <p className="mt-1 text-sm text-foreground-muted">conversaciones resueltas o cerradas</p>
            </div>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-md bg-surface-muted px-3 py-2">
                <div className="flex items-center gap-1.5 text-success-foreground">
                  <ArrowUpRight className="size-3.5" />
                  <span className="font-medium">{resolutionPct}</span>
                </div>
                <p className="mt-1 text-xs text-foreground-muted">resolución</p>
              </div>
              <div className="rounded-md bg-surface-muted px-3 py-2">
                <div className="flex items-center gap-1.5 text-warning-foreground">
                  <ArrowDownRight className="size-3.5" />
                  <span className="font-medium">{escalationPct}</span>
                </div>
                <p className="mt-1 text-xs text-foreground-muted">escalación</p>
              </div>
            </div>
          </div>
          <SupportLineChart />
        </Card>

        <Card className="p-(--density-card-p)">
          <div className="flex items-center justify-between">
            <p className="text-sm font-semibold text-foreground">Estado de conversaciones</p>
            <BarChart3 className="size-4 text-foreground-muted" />
          </div>
          <div className="mt-5 space-y-4">
            {[
              ['Abiertas', data.by_status.open],
              ['Pendientes', data.by_status.pending],
              ['Escaladas', data.by_status.escalated],
              ['Resueltas', data.by_status.resolved],
              ['Cerradas', data.by_status.closed],
            ].map(([label, value]) => (
              <div key={label} className="flex items-center justify-between gap-4">
                <span className="text-sm text-foreground-body">{label}</span>
                <span className="text-sm font-medium tabular-nums text-foreground">{value}</span>
              </div>
            ))}
          </div>
          <div className="mt-6 flex items-center gap-2 rounded-md bg-surface-muted px-3 py-3">
            <div className="grid size-7 place-items-center rounded-full bg-accent-subtle">
              <span className="text-xs font-semibold text-accent-foreground">+{active}</span>
            </div>
            <span className="text-sm text-foreground-body">requieren seguimiento ahora</span>
          </div>
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <MiniCard
          label="Activas"
          value={active}
          sub={`${data.by_status.open} abiertas · ${data.by_status.pending} pendientes`}
          icon={Inbox}
        />
        <MiniCard
          label="Escaladas"
          value={data.by_status.escalated}
          sub="requieren atención humana del equipo CX"
          icon={CircleAlert}
        />
        <Card className="p-(--density-card-p)">
          <div>
            <p className="text-sm font-medium text-foreground">Total histórico</p>
            <p className="mt-2 text-2xl font-semibold tabular-nums text-foreground">{data.total}</p>
          </div>
          <div className="mt-4 h-2 overflow-hidden rounded-full bg-surface-muted">
            <div className="h-full rounded-full bg-accent" style={{ width: `${Math.min(data.resolution_rate * 100, 100)}%` }} />
          </div>
          <p className="mt-3 border-t border-border-subtle pt-3 text-xs text-foreground-muted">
            ratio de resolución acumulada
          </p>
        </Card>
      </div>
    </div>
  )
}
