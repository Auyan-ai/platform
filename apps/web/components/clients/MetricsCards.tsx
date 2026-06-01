'use client'

import { useMemo, useState, type MouseEvent } from 'react'
import { useMetrics, type TenantMetrics } from '@/lib/api/hooks/metrics'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Inbox,
} from 'lucide-react'

interface MetricsCardsProps {
  tenantId: string
}

const SKELETON_KEYS = ['metrics-a', 'metrics-b', 'metrics-c', 'metrics-d']
const WINDOW_KEYS = ['30d', '7d', '24h'] as const
const WINDOW_CONFIG = {
  '30d': { label: 'Últimos 30 días', granularity: 'day', points: 30 },
  '7d': { label: 'Últimos 7 días', granularity: 'day', points: 7 },
  '24h': { label: 'Último día', granularity: 'hour', points: 24 },
} as const

type ResolutionWindow = TenantMetrics['resolution_windows'][number]
type ResolutionPoint = ResolutionWindow['points'][number]
type WindowKey = (typeof WINDOW_KEYS)[number]

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
      <p className="mt-4 border-t border-border-subtle pt-3 text-xs text-foreground-muted">{sub}</p>
    </Card>
  )
}

function formatPercent(value: number) {
  return `${(value * 100).toFixed(1)}%`
}

function formatBucketLabel(point: ResolutionPoint, granularity: ResolutionWindow['granularity']) {
  const date = new Date(point.bucket)
  if (Number.isNaN(date.getTime())) return point.bucket

  if (granularity === 'hour') {
    return new Intl.DateTimeFormat('es', {
      hour: '2-digit',
      minute: '2-digit',
    }).format(date)
  }

  return new Intl.DateTimeFormat('es', {
    day: '2-digit',
    month: 'short',
  }).format(date)
}

function formatTooltipLabel(point: ResolutionPoint, granularity: ResolutionWindow['granularity']) {
  const date = new Date(point.bucket)
  if (Number.isNaN(date.getTime())) return point.bucket

  if (granularity === 'hour') {
    return new Intl.DateTimeFormat('es', {
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    }).format(date)
  }

  return new Intl.DateTimeFormat('es', {
    weekday: 'short',
    day: '2-digit',
    month: 'short',
  }).format(date)
}

function buildLinePath(points: Array<{ x: number; y: number }>) {
  if (points.length === 0) return ''
  return points.map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x} ${point.y}`).join(' ')
}

function getAdjacentWindowKey(currentKey: WindowKey, direction: -1 | 1): WindowKey {
  const currentIndex = WINDOW_KEYS.indexOf(currentKey)
  const nextIndex = (currentIndex + direction + WINDOW_KEYS.length) % WINDOW_KEYS.length
  return WINDOW_KEYS[nextIndex]
}

function buildEmptyPoints(key: WindowKey): ResolutionPoint[] {
  const config = WINDOW_CONFIG[key]
  const now = new Date()

  return Array.from({ length: config.points }, (_, index) => {
    const bucket = new Date(now)
    if (config.granularity === 'hour') {
      bucket.setMinutes(0, 0, 0)
      bucket.setHours(bucket.getHours() - (config.points - 1 - index))
    } else {
      bucket.setHours(0, 0, 0, 0)
      bucket.setDate(bucket.getDate() - (config.points - 1 - index))
    }

    return {
      bucket: bucket.toISOString(),
      conversations: 0,
      resolved: 0,
      escalated: 0,
      resolution_rate: 0,
      escalation_rate: 0,
    }
  })
}

function ResolutionLineChart({ window }: { window: ResolutionWindow }) {
  const [activeIndex, setActiveIndex] = useState<number | null>(null)
  const chart = useMemo(() => {
    const width = 640
    const height = 246
    const padding = { top: 18, right: 20, bottom: 42, left: 38 }
    const innerWidth = width - padding.left - padding.right
    const innerHeight = height - padding.top - padding.bottom
    const values = window.points.flatMap((point) => [point.resolved, point.escalated])
    const maxValue = Math.max(1, ...values)

    const plotted = window.points.map((point, index) => {
      const x =
        window.points.length === 1
          ? padding.left + innerWidth / 2
          : padding.left + (index / (window.points.length - 1)) * innerWidth
      return {
        point,
        x,
        resolvedY: padding.top + ((maxValue - point.resolved) / maxValue) * innerHeight,
        escalatedY: padding.top + ((maxValue - point.escalated) / maxValue) * innerHeight,
      }
    })

    const resolvedPoints = plotted.map((item) => ({ x: item.x, y: item.resolvedY }))
    const escalatedPoints = plotted.map((item) => ({ x: item.x, y: item.escalatedY }))
    const resolvedPath = buildLinePath(resolvedPoints)
    const escalatedPath = buildLinePath(escalatedPoints)
    const areaPath =
      resolvedPoints.length > 0
        ? `${resolvedPath} L ${resolvedPoints.at(-1)?.x ?? padding.left} ${height - padding.bottom} L ${resolvedPoints[0].x} ${height - padding.bottom} Z`
        : ''

    return {
      width,
      height,
      padding,
      innerHeight,
      maxValue,
      plotted,
      resolvedPath,
      escalatedPath,
      areaPath,
      grid: [0, 0.25, 0.5, 0.75, 1].map((step) => ({
        y: padding.top + step * innerHeight,
        label: Math.round(maxValue * (1 - step)).toString(),
      })),
    }
  }, [window])

  const active = activeIndex === null ? null : chart.plotted[activeIndex]
  const axisPoints = Array.from(
    new Map(
      [window.points[0], window.points[Math.floor(window.points.length / 2)], window.points.at(-1)]
        .filter(Boolean)
        .map((point) => [point?.bucket, point]),
    ).values(),
  ) as ResolutionPoint[]

  function handleMouseMove(event: MouseEvent<SVGSVGElement>) {
    if (chart.plotted.length === 0) return
    const rect = event.currentTarget.getBoundingClientRect()
    const x = ((event.clientX - rect.left) / rect.width) * chart.width
    const nearest = chart.plotted.reduce(
      (best, item, index) => {
        const distance = Math.abs(item.x - x)
        return distance < best.distance ? { index, distance } : best
      },
      { index: 0, distance: Number.POSITIVE_INFINITY },
    )
    setActiveIndex(nearest.index)
  }

  return (
    <div className="relative mt-6 overflow-hidden rounded-md bg-surface">
      <div className="absolute left-4 top-3 z-10 flex items-center gap-4 text-xs text-foreground-muted">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-0.5 w-4 rounded-full bg-accent" />
          resueltas
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-0.5 w-4 rounded-full bg-warning" />
          escaladas
        </span>
      </div>
      <svg
        viewBox={`0 0 ${chart.width} ${chart.height}`}
        className="block h-64 w-full"
        role="img"
        aria-label={`Resolución IA en ${window.label}`}
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setActiveIndex(null)}
      >
        <defs>
          <linearGradient id={`resolutionFill-${window.key}`} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="var(--color-accent)" stopOpacity="0.12" />
            <stop offset="72%" stopColor="var(--color-accent)" stopOpacity="0.035" />
            <stop offset="100%" stopColor="var(--color-accent)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {chart.grid.map((line) => (
          <g key={line.y}>
            <line
              x1={chart.padding.left}
              x2={chart.width - chart.padding.right}
              y1={line.y}
              y2={line.y}
              stroke="var(--color-border-subtle)"
              strokeDasharray="3 5"
            />
            <text
              x={chart.padding.left - 10}
              y={line.y + 4}
              textAnchor="end"
              className="fill-foreground-subtle text-[10px]"
            >
              {line.label}
            </text>
          </g>
        ))}
        <path d={chart.areaPath} fill={`url(#resolutionFill-${window.key})`} />
        <path
          d={chart.escalatedPath}
          fill="none"
          stroke="var(--color-warning)"
          strokeDasharray="5 5"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="2"
        />
        <path
          d={chart.resolvedPath}
          fill="none"
          stroke="var(--color-accent-foreground)"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="2.8"
        />
        {chart.plotted.length <= 7
          ? chart.plotted.map((item) => (
              <g key={`markers-${item.point.bucket}`}>
                <circle
                  cx={item.x}
                  cy={item.resolvedY}
                  r="3"
                  fill="var(--color-surface)"
                  stroke="var(--color-accent-foreground)"
                  strokeWidth="1.8"
                />
                <circle
                  cx={item.x}
                  cy={item.escalatedY}
                  r="2.8"
                  fill="var(--color-surface)"
                  stroke="var(--color-warning)"
                  strokeWidth="1.6"
                />
              </g>
            ))
          : null}
        {chart.plotted.map((item, index) => (
          <g key={item.point.bucket}>
            <rect
              x={index === 0 ? 0 : item.x - 10}
              y={0}
              width={index === 0 || index === chart.plotted.length - 1 ? 20 : 20}
              height={chart.height}
              fill="transparent"
              className="cursor-crosshair"
              onMouseEnter={() => setActiveIndex(index)}
              onFocus={() => setActiveIndex(index)}
              tabIndex={0}
            />
            {activeIndex === index && (
              <>
                <line
                  x1={item.x}
                  x2={item.x}
                  y1={chart.padding.top}
                  y2={chart.height - chart.padding.bottom}
                  stroke="var(--color-border-strong)"
                  strokeDasharray="4 4"
                />
                <circle
                  cx={item.x}
                  cy={item.resolvedY}
                  r="4"
                  fill="var(--color-surface)"
                  stroke="var(--color-accent-foreground)"
                  strokeWidth="2"
                />
                <circle
                  cx={item.x}
                  cy={item.escalatedY}
                  r="3.5"
                  fill="var(--color-surface)"
                  stroke="var(--color-warning)"
                  strokeWidth="2"
                />
              </>
            )}
          </g>
        ))}
      </svg>
      <div className="absolute bottom-3 left-10 right-5 flex justify-between text-xs text-foreground-subtle">
        {axisPoints.map((point) => (
          <span key={`${window.key}-${point.bucket}`}>
            {formatBucketLabel(point, window.granularity)}
          </span>
        ))}
      </div>
      {active ? (
        <div
          className="pointer-events-none absolute top-12 z-20 min-w-40 rounded-md border border-border bg-surface px-3 py-2 text-xs shadow-sm"
          style={{
            left: `${(active.x / chart.width) * 100}%`,
            transform: active.x > chart.width * 0.72 ? 'translateX(-100%)' : 'translateX(-8px)',
          }}
        >
          <p className="font-medium text-foreground">
            {formatTooltipLabel(active.point, window.granularity)}
          </p>
          <div className="mt-2 space-y-1 text-foreground-muted">
            <div className="flex justify-between gap-5">
              <span>Resueltas</span>
              <span className="font-medium tabular-nums text-foreground">
                {active.point.resolved}
              </span>
            </div>
            <div className="flex justify-between gap-5">
              <span>Escaladas</span>
              <span className="font-medium tabular-nums text-foreground">
                {active.point.escalated}
              </span>
            </div>
            <div className="flex justify-between gap-5 border-t border-border-subtle pt-1">
              <span>Conversaciones</span>
              <span className="font-medium tabular-nums text-foreground">
                {active.point.conversations}
              </span>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}

function buildFallbackWindow(data: TenantMetrics, key: WindowKey): ResolutionWindow {
  const config = WINDOW_CONFIG[key]
  const handled = data.by_status.resolved + data.by_status.closed
  const points = buildEmptyPoints(key)
  const lastPoint = points.at(-1)
  if (lastPoint) {
    lastPoint.conversations = data.total
    lastPoint.resolved = handled
    lastPoint.escalated = data.by_status.escalated
    lastPoint.resolution_rate = data.resolution_rate
    lastPoint.escalation_rate = data.escalation_rate
  }

  return {
    key,
    label: config.label,
    granularity: config.granularity,
    total: data.total,
    resolved: handled,
    escalated: data.by_status.escalated,
    resolution_rate: data.resolution_rate,
    escalation_rate: data.escalation_rate,
    points,
  }
}

export function MetricsCards({ tenantId }: MetricsCardsProps) {
  const { data, isLoading, isError } = useMetrics(tenantId)
  const [selectedKey, setSelectedKey] = useState<WindowKey>('30d')

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
  const resolutionWindows = data.resolution_windows ?? []
  const windows = WINDOW_KEYS.map(
    (key) =>
      resolutionWindows.find((window) => window.key === key) ?? buildFallbackWindow(data, key),
  )
  const selectedWindow = windows.find((window) => window.key === selectedKey) ?? windows[0]
  const resolutionPct = formatPercent(selectedWindow.resolution_rate)
  const escalationPct = formatPercent(selectedWindow.escalation_rate)
  const handled = selectedWindow.resolved

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-[1.08fr_0.92fr]">
        <Card className="overflow-hidden p-(--density-card-p)">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <p className="text-sm font-medium text-foreground">Resolución IA</p>
              </div>
              <p className="mt-3 text-4xl font-semibold tabular-nums text-foreground">{handled}</p>
              <p className="mt-1 text-sm text-foreground-muted">
                conversaciones resueltas o cerradas
              </p>
            </div>
            <div className="flex flex-col items-end gap-3">
              <div
                className="inline-flex h-8 items-center rounded-md border border-border bg-surface px-1 text-xs shadow-sm"
                aria-label="Rango de Resolución IA"
              >
                <button
                  type="button"
                  className="grid size-6 place-items-center rounded-sm text-foreground-subtle transition-colors hover:bg-surface-muted hover:text-foreground"
                  aria-label="Periodo anterior"
                  onClick={() => setSelectedKey(getAdjacentWindowKey(selectedWindow.key, -1))}
                >
                  <ChevronLeft className="size-3.5" />
                </button>
                <button
                  type="button"
                  className="h-6 min-w-28 px-2 text-center font-medium tabular-nums text-foreground-body"
                  aria-label={`Rango actual: ${selectedWindow.label}. Cambiar al siguiente periodo`}
                  onClick={() => setSelectedKey(getAdjacentWindowKey(selectedWindow.key, 1))}
                >
                  {selectedWindow.label}
                </button>
                <button
                  type="button"
                  className="grid size-6 place-items-center rounded-sm text-foreground-subtle transition-colors hover:bg-surface-muted hover:text-foreground"
                  aria-label="Periodo siguiente"
                  onClick={() => setSelectedKey(getAdjacentWindowKey(selectedWindow.key, 1))}
                >
                  <ChevronRight className="size-3.5" />
                </button>
              </div>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-md border border-border-subtle bg-surface-muted px-3 py-2">
                  <div className="flex items-center gap-1.5 text-accent-foreground">
                    <ArrowUpRight className="size-3.5" />
                    <span className="font-medium tabular-nums">{resolutionPct}</span>
                  </div>
                  <p className="mt-1 text-xs text-foreground-muted">resolución</p>
                </div>
                <div className="rounded-md border border-border-subtle bg-surface-muted px-3 py-2">
                  <div className="flex items-center gap-1.5 text-warning-foreground">
                    <ArrowDownRight className="size-3.5" />
                    <span className="font-medium tabular-nums">{escalationPct}</span>
                  </div>
                  <p className="mt-1 text-xs text-foreground-muted">escalación</p>
                </div>
              </div>
            </div>
          </div>
          <ResolutionLineChart window={selectedWindow} />
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
            <div
              className="h-full rounded-full bg-accent"
              style={{ width: `${Math.min(data.resolution_rate * 100, 100)}%` }}
            />
          </div>
          <p className="mt-3 border-t border-border-subtle pt-3 text-xs text-foreground-muted">
            ratio de resolución acumulada
          </p>
        </Card>
      </div>
    </div>
  )
}
