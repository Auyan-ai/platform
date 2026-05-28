'use client'

import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { type WeeklyReport, useWeeklyReports } from '@/lib/api/hooks/tenant-context'
import { cn } from '@/lib/utils'
import { FileBarChart2 } from 'lucide-react'
import { useMemo, useState } from 'react'

function numberMetric(report: WeeklyReport, path: string[], fallback = 0) {
  let value: unknown = report.metrics
  for (const key of path) {
    if (!value || typeof value !== 'object' || !(key in value)) return fallback
    value = (value as Record<string, unknown>)[key]
  }
  return typeof value === 'number' ? value : fallback
}

function dateRange(report: WeeklyReport) {
  return `${report.week_start} a ${report.week_end}`
}

export function WeeklyReportHistory({ tenantId }: { tenantId: string }) {
  const [activeId, setActiveId] = useState<string | null>(null)
  const { data, isLoading, isError } = useWeeklyReports(tenantId, 'sent')

  const active = useMemo(() => {
    if (!data?.length) return null
    return data.find((report) => report.id === activeId) ?? data[0]
  }, [activeId, data])

  if (isLoading) return <Skeleton className="h-[560px]" />

  if (isError) {
    return (
      <div className="rounded-md border border-danger bg-danger-subtle px-4 py-3 text-sm text-danger-foreground">
        No se pudieron cargar los reportes.
      </div>
    )
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
      <Card className="overflow-hidden p-2">
        <div className="border-b border-border-subtle px-3 py-3">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <FileBarChart2 className="size-4 text-accent-foreground" />
              <p className="text-sm font-semibold text-foreground">Historial</p>
            </div>
            <Badge variant={(data?.length ?? 0) > 0 ? 'success' : 'secondary'}>
              {data?.length ?? 0}
            </Badge>
          </div>
        </div>
        <nav className="max-h-[500px] space-y-1 overflow-y-auto p-2">
          {(data ?? []).map((report) => {
            const isActive = active?.id === report.id
            return (
              <button
                key={report.id}
                type="button"
                onClick={() => setActiveId(report.id)}
                className={cn(
                  'w-full rounded-sm px-3 py-2 text-left transition-colors',
                  isActive ? 'bg-accent-subtle text-accent-foreground' : 'hover:bg-surface-muted',
                )}
              >
                <p className="truncate text-sm font-medium">{dateRange(report)}</p>
                <p className="mt-1 truncate text-xs text-foreground-muted">
                  {report.sent_at ? `Enviado ${report.sent_at.slice(0, 10)}` : 'Enviado'}
                </p>
              </button>
            )
          })}
          {data?.length === 0 && (
            <p className="px-3 py-4 text-sm text-foreground-muted">Aún no hay reportes enviados.</p>
          )}
        </nav>
      </Card>

      <Card className="min-h-[560px] p-(--density-card-p)">
        {active ? (
          <div className="space-y-5">
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-xl font-semibold text-foreground">{active.subject}</h1>
                <Badge variant="success">Enviado</Badge>
              </div>
              <p className="mt-1 text-sm text-foreground-muted">{dateRange(active)}</p>
            </div>

            <div className="grid gap-3 md:grid-cols-4">
              <Metric
                label="Conversaciones"
                value={numberMetric(active, ['volume', 'conversations'])}
              />
              <Metric label="Mensajes" value={numberMetric(active, ['volume', 'messages'])} />
              <Metric
                label="Resolución"
                value={`${numberMetric(active, ['resolution_rate']).toFixed(1)}%`}
              />
              <Metric
                label="Escalación"
                value={`${numberMetric(active, ['escalation_rate']).toFixed(1)}%`}
              />
            </div>

            <div className="whitespace-pre-wrap rounded-md border border-border-subtle bg-surface-muted p-4 text-sm leading-6 text-foreground-body">
              {active.narrative}
            </div>
          </div>
        ) : (
          <div className="flex min-h-[480px] items-center justify-center text-sm text-foreground-muted">
            Sin reportes disponibles.
          </div>
        )}
      </Card>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-md border border-border-subtle bg-surface-muted px-3 py-3">
      <p className="text-xs font-medium uppercase tracking-wider text-foreground-muted">{label}</p>
      <p className="mt-2 text-xl font-semibold tabular-nums text-foreground">{value}</p>
    </div>
  )
}
