'use client'

import { ConversationList } from '@/components/inbox/ConversationList'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { type TenantInsightBreakdownItem, useTenantInsights } from '@/lib/api/hooks/tenant-context'
import { cn } from '@/lib/utils'
import { Activity, CircleDotDashed, Filter } from 'lucide-react'

const DONUT_COLORS = [
  'var(--color-accent)',
  'var(--color-success)',
  'var(--color-warning)',
  'var(--color-danger)',
  'var(--color-foreground-muted)',
  'var(--color-border-strong)',
]

function humanizeLabel(label: string) {
  return label.replaceAll('_', ' ')
}

function total(items: TenantInsightBreakdownItem[]) {
  return items.reduce((sum, item) => sum + item.count, 0)
}

function Donut({ items }: { items: TenantInsightBreakdownItem[] }) {
  const grandTotal = total(items)
  let offset = 25

  if (grandTotal === 0) {
    return (
      <div className="grid size-36 place-items-center rounded-full border border-border-subtle bg-surface-muted text-xs text-foreground-muted">
        Sin motivos
      </div>
    )
  }

  return (
    <svg
      viewBox="0 0 42 42"
      className="size-36 -rotate-90"
      role="img"
      aria-label="Motivos principales"
    >
      <circle
        cx="21"
        cy="21"
        r="15.915"
        fill="transparent"
        stroke="var(--color-surface-muted)"
        strokeWidth="7"
      />
      {items.map((item, index) => {
        const percent = (item.count / grandTotal) * 100
        const strokeDasharray = `${percent} ${100 - percent}`
        const strokeDashoffset = offset
        offset -= percent
        return (
          <circle
            key={item.label}
            cx="21"
            cy="21"
            r="15.915"
            fill="transparent"
            stroke={DONUT_COLORS[index % DONUT_COLORS.length]}
            strokeDasharray={strokeDasharray}
            strokeDashoffset={strokeDashoffset}
            strokeWidth="7"
          />
        )
      })}
    </svg>
  )
}

function BreakdownList({ items }: { items: TenantInsightBreakdownItem[] }) {
  const grandTotal = total(items)

  if (items.length === 0) {
    return <p className="text-sm text-foreground-muted">Sin datos suficientes.</p>
  }

  return (
    <div className="space-y-2">
      {items.map((item, index) => {
        const pct = grandTotal > 0 ? Math.round((item.count / grandTotal) * 100) : 0
        return (
          <div key={item.label} className="flex items-center gap-3">
            <span
              className="size-2.5 rounded-full"
              style={{ background: DONUT_COLORS[index % DONUT_COLORS.length] }}
            />
            <span className="min-w-0 flex-1 truncate text-sm text-foreground-body">
              {humanizeLabel(item.label)}
            </span>
            <span className="text-sm font-medium tabular-nums text-foreground">{item.count}</span>
            <span className="w-9 text-right text-xs tabular-nums text-foreground-muted">
              {pct}%
            </span>
          </div>
        )
      })}
    </div>
  )
}

function TimelineHeatmap({
  timeline,
}: {
  timeline: Array<{ date: string; conversations: number }>
}) {
  const max = Math.max(...timeline.map((point) => point.conversations), 1)

  return (
    <div className="grid grid-cols-7 gap-2">
      {timeline.map((point) => {
        const intensity = point.conversations / max
        return (
          <div key={point.date} className="space-y-1.5">
            <div
              className={cn(
                'h-8 rounded-sm border border-border-subtle',
                intensity === 0 && 'bg-surface-muted',
                intensity > 0 && intensity < 0.34 && 'bg-accent-subtle',
                intensity >= 0.34 && intensity < 0.67 && 'bg-accent/60',
                intensity >= 0.67 && 'bg-accent',
              )}
              title={`${point.conversations} conversaciones · ${point.date}`}
            />
            <p className="text-center text-[10px] tabular-nums text-foreground-muted">
              {point.date.slice(5)}
            </p>
          </div>
        )
      })}
    </div>
  )
}

export function ClientInsightsExplorer({ tenantId }: { tenantId: string }) {
  const { data, isLoading, isError } = useTenantInsights(tenantId, 14)

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-medium uppercase tracking-wider text-foreground-muted">
          Actividad
        </p>
        <h1 className="mt-1 text-2xl font-semibold text-foreground">Insights</h1>
        <p className="mt-1 max-w-2xl text-sm text-foreground-muted">
          Conversaciones, canales y motivos más frecuentes de los últimos 14 días.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
        <Card className="p-(--density-card-p)">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Activity className="size-4 text-accent-foreground" />
              <h2 className="text-sm font-semibold text-foreground">Actividad por día</h2>
            </div>
            <span className="text-xs text-foreground-muted">últimos 14 días</span>
          </div>
          {isLoading ? (
            <Skeleton className="h-28" />
          ) : isError || !data ? (
            <div className="rounded-md bg-danger-subtle px-3 py-2 text-sm text-danger-foreground">
              No se pudieron cargar los insights.
            </div>
          ) : (
            <TimelineHeatmap timeline={data.timeline} />
          )}
        </Card>

        <Card className="p-(--density-card-p)">
          <div className="mb-4 flex items-center gap-2">
            <CircleDotDashed className="size-4 text-accent-foreground" />
            <h2 className="text-sm font-semibold text-foreground">Motivos principales</h2>
          </div>
          {isLoading ? (
            <Skeleton className="h-36" />
          ) : (
            <div className="flex items-center gap-5">
              <Donut items={data?.top_intents ?? []} />
              <div className="min-w-0 flex-1">
                <BreakdownList items={data?.top_intents ?? []} />
              </div>
            </div>
          )}
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-(--density-card-p)">
          <div className="mb-4 flex items-center gap-2">
            <Filter className="size-4 text-foreground-muted" />
            <h2 className="text-sm font-semibold text-foreground">Canales</h2>
          </div>
          {isLoading ? (
            <Skeleton className="h-24" />
          ) : (
            <BreakdownList items={data?.by_channel ?? []} />
          )}
        </Card>

        <Card className="p-(--density-card-p)">
          <div className="mb-4 flex items-center gap-2">
            <Filter className="size-4 text-foreground-muted" />
            <h2 className="text-sm font-semibold text-foreground">Estados</h2>
          </div>
          {isLoading ? (
            <Skeleton className="h-24" />
          ) : (
            <BreakdownList items={data?.by_status ?? []} />
          )}
        </Card>
      </div>

      <ConversationList
        tenantId={tenantId}
        basePath={`/clients/${tenantId}/insights`}
        title="Drill-down"
        description="Conversaciones con filtros de estado y panel de razonamiento en detalle."
      />
    </div>
  )
}
