'use client'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useApprovals } from '@/lib/api/hooks/approvals'
import { useMetrics } from '@/lib/api/hooks/metrics'
import { type WeeklyReport, useWeeklyReports } from '@/lib/api/hooks/tenant-context'
import { useMyTenant } from '@/lib/api/hooks/tenants'
import { useUsage } from '@/lib/api/hooks/usage'
import { cn } from '@/lib/utils'
import { AlertTriangle, ArrowRight, CheckCircle2, FileBarChart2, Radio } from 'lucide-react'
import Link from 'next/link'

const LIFECYCLE_LABELS: Record<string, string> = {
  initial: 'Initial',
  discovery: 'Discovery',
  building: 'Building',
  shadow: 'Shadow',
  ramping: 'Ramping',
  active: 'Active',
  paused: 'Paused',
  churned: 'Churned',
}

const AGENT_PROGRESS_PHASES = [
  'initial',
  'discovery',
  'building',
  'shadow',
  'ramping',
  'active',
] as const

function firstNarrativeLine(report: WeeklyReport | null) {
  if (!report?.narrative.trim()) return 'Aún no hay headline disponible para esta semana.'
  return (
    report.narrative
      .split('\n')
      .map((line) => line.trim())
      .find(Boolean) ?? 'Aún no hay headline disponible para esta semana.'
  )
}

function formatDate(date: string | null | undefined) {
  if (!date) return 'sin fecha'
  return new Intl.DateTimeFormat('es', {
    day: '2-digit',
    month: 'short',
  }).format(new Date(date))
}

function ActivityHeatmap({ tenantId }: { tenantId: string }) {
  const { data, isLoading, isError } = useUsage(tenantId, 14)
  const maxRequests = Math.max(...(data?.history.map((day) => day.request_count) ?? [0]), 1)

  if (isLoading) return <Skeleton className="h-28" />

  if (isError || !data) {
    return (
      <div className="rounded-md bg-danger-subtle px-3 py-2 text-sm text-danger-foreground">
        No se pudo cargar actividad.
      </div>
    )
  }

  return (
    <div className="grid grid-cols-7 gap-2">
      {data.history.slice(-14).map((day) => {
        const intensity = day.request_count / maxRequests
        return (
          <div key={day.date} className="space-y-1.5">
            <div
              className={cn(
                'h-8 rounded-sm border border-border-subtle',
                intensity === 0 && 'bg-surface-muted',
                intensity > 0 && intensity < 0.34 && 'bg-accent-subtle',
                intensity >= 0.34 && intensity < 0.67 && 'bg-accent/60',
                intensity >= 0.67 && 'bg-accent',
              )}
              title={`${day.request_count} requests · ${day.date}`}
            />
            <p className="text-center text-[10px] tabular-nums text-foreground-muted">
              {formatDate(day.date)}
            </p>
          </div>
        )
      })}
    </div>
  )
}

function AgentLifecycleProgress({
  lifecycle,
  isLoading,
}: {
  lifecycle: string
  isLoading: boolean
}) {
  if (isLoading) {
    return (
      <div className="space-y-2">
        <p className="text-xs font-medium text-foreground-muted">Fase del agente</p>
        <Skeleton className="h-6 w-64" />
      </div>
    )
  }

  if (lifecycle === 'active') {
    return (
      <div className="space-y-2">
        <p className="text-xs font-medium text-foreground-muted">Estado del agente</p>
        <Badge variant="default">Active</Badge>
      </div>
    )
  }

  if (!AGENT_PROGRESS_PHASES.includes(lifecycle as (typeof AGENT_PROGRESS_PHASES)[number])) {
    return (
      <div className="space-y-2">
        <p className="text-xs font-medium text-foreground-muted">Estado del agente</p>
        <Badge variant="secondary">{LIFECYCLE_LABELS[lifecycle] ?? lifecycle}</Badge>
      </div>
    )
  }

  const currentIndex = AGENT_PROGRESS_PHASES.indexOf(
    lifecycle as (typeof AGENT_PROGRESS_PHASES)[number],
  )

  return (
    <div className="space-y-2">
      <p className="text-xs font-medium text-foreground-muted">Fase del agente</p>
      <div className="flex flex-wrap items-center gap-1.5">
        {AGENT_PROGRESS_PHASES.map((phase, index) => {
          const isCurrent = phase === lifecycle
          const isComplete = index < currentIndex

          return (
            <Badge
              key={phase}
              variant={isCurrent ? 'default' : 'muted'}
              aria-current={isCurrent ? 'step' : undefined}
              className={cn(
                !isCurrent && 'font-normal',
                isComplete && 'gap-1 text-foreground-body',
              )}
            >
              {isComplete && (
                <CheckCircle2
                  aria-hidden="true"
                  className="size-3.5 shrink-0 text-foreground-muted"
                />
              )}
              {LIFECYCLE_LABELS[phase]}
            </Badge>
          )
        })}
      </div>
    </div>
  )
}

export function ClientHomeSummary({ tenantId }: { tenantId: string }) {
  const tenant = useMyTenant()
  const metrics = useMetrics(tenantId)
  const reports = useWeeklyReports(tenantId, 'sent')
  const approvals = useApprovals({ tenantId, status: 'pending', limit: 5 })

  const latestReport = reports.data?.[0] ?? null
  const lifecycle = tenant.data?.agent_lifecycle_state ?? 'initial'
  const pendingApprovals = approvals.data?.approvals.length ?? 0
  const escalated = metrics.data?.by_status.escalated ?? 0
  const activeConversations =
    (metrics.data?.by_status.open ?? 0) + (metrics.data?.by_status.pending ?? 0)
  const hasAlerts = pendingApprovals > 0 || escalated > 0

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
      <Card className="p-(--density-card-p)">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <AgentLifecycleProgress lifecycle={lifecycle} isLoading={tenant.isLoading} />
            <h1 className="mt-4 text-2xl font-semibold text-foreground">Home</h1>
            <p className="mt-1 max-w-2xl text-sm text-foreground-muted">
              KPIs, actividad y reporte semanal del soporte IA de tu cuenta.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-3 text-sm">
            <div className="rounded-md bg-surface-muted px-3 py-2">
              <p className="text-xs text-foreground-muted">Seguimiento</p>
              <p className="mt-1 text-xl font-semibold tabular-nums text-foreground">
                {metrics.isLoading ? '...' : activeConversations}
              </p>
            </div>
            <div className="rounded-md bg-surface-muted px-3 py-2">
              <p className="text-xs text-foreground-muted">Alertas</p>
              <p className="mt-1 text-xl font-semibold tabular-nums text-foreground">
                {metrics.isLoading || approvals.isLoading ? '...' : pendingApprovals + escalated}
              </p>
            </div>
          </div>
        </div>

        <div className="mt-6 border-t border-border-subtle pt-5">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Radio className="size-4 text-accent-foreground" />
              <p className="text-sm font-semibold text-foreground">Actividad reciente</p>
            </div>
            <span className="text-xs text-foreground-muted">últimos 14 días</span>
          </div>
          <ActivityHeatmap tenantId={tenantId} />
        </div>
      </Card>

      <div className="space-y-4">
        <Card className="p-(--density-card-p)">
          <div className="flex items-center gap-2">
            <FileBarChart2 className="size-4 text-accent-foreground" />
            <h2 className="text-sm font-semibold text-foreground">Reporte semanal</h2>
          </div>
          {reports.isLoading ? (
            <Skeleton className="mt-4 h-20" />
          ) : latestReport ? (
            <div className="mt-4 space-y-3">
              <p className="text-sm font-medium text-foreground">{latestReport.subject}</p>
              <p className="line-clamp-3 text-sm leading-6 text-foreground-muted">
                {firstNarrativeLine(latestReport)}
              </p>
              <div className="flex items-center justify-between gap-3 border-t border-border-subtle pt-3">
                <span className="text-xs text-foreground-muted">
                  {formatDate(latestReport.week_start)} - {formatDate(latestReport.week_end)}
                </span>
                <Button asChild size="sm" variant="secondary">
                  <Link href={`/clients/${tenantId}/reports`}>
                    Abrir
                    <ArrowRight className="size-3.5" />
                  </Link>
                </Button>
              </div>
            </div>
          ) : (
            <p className="mt-4 text-sm leading-6 text-foreground-muted">
              El primer reporte aparecerá aquí cuando Auyan lo apruebe y envíe.
            </p>
          )}
        </Card>

        <Card className="p-(--density-card-p)">
          <div className="flex items-center gap-2">
            {hasAlerts ? (
              <AlertTriangle className="size-4 text-warning-foreground" />
            ) : (
              <CheckCircle2 className="size-4 text-success-foreground" />
            )}
            <h2 className="text-sm font-semibold text-foreground">Alertas</h2>
          </div>
          <div className="mt-4 space-y-3 text-sm">
            <div className="flex items-center justify-between gap-3">
              <span className="text-foreground-body">Aprobaciones L3 pendientes</span>
              <Badge variant={pendingApprovals > 0 ? 'warning' : 'muted'}>{pendingApprovals}</Badge>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-foreground-body">Conversaciones escaladas</span>
              <Badge variant={escalated > 0 ? 'danger' : 'muted'}>{escalated}</Badge>
            </div>
          </div>
        </Card>
      </div>
    </div>
  )
}
