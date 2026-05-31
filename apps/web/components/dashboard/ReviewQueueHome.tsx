'use client'

import { CreateTenantDialog } from '@/components/dashboard/CreateTenantDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useAdminReviewQueue } from '@/lib/api/hooks/tenants'
import { cn } from '@/lib/utils'
import type { components } from '@auyan/shared/api-types'
import { CheckCircle2, ClipboardCheck, FileBarChart2, FileText, Sparkles } from 'lucide-react'
import Link from 'next/link'
import { useMemo, useState } from 'react'

type QueueFilter = 'all' | 'qa_km' | 'aide' | 'ops_manager'
type QueueType = 'kb' | 'weekly' | 'approvals' | 'proposals'
type ReviewQueueItem = components['schemas']['AdminReviewQueueItem']

const FILTER_LABELS: Record<QueueFilter, string> = {
  all: 'Todos',
  qa_km: 'QA-KM',
  aide: 'AIDE',
  ops_manager: 'Ops',
}

const ROLE_TYPES: Record<QueueFilter, QueueType[]> = {
  all: ['kb', 'weekly', 'approvals', 'proposals'],
  qa_km: ['kb', 'proposals'],
  aide: ['kb', 'approvals', 'proposals'],
  ops_manager: ['weekly', 'approvals'],
}

const TYPE_META: Record<QueueType, { label: string; section: string; icon: typeof FileText }> = {
  kb: { label: 'KB pending', section: 'knowledge', icon: FileText },
  weekly: { label: 'Reportes', section: 'reports', icon: FileBarChart2 },
  approvals: { label: 'Aprobaciones L3', section: 'approvals', icon: ClipboardCheck },
  proposals: { label: 'Proposals', section: 'proposals', icon: Sparkles },
}

function countForType(item: ReviewQueueItem, type: QueueType) {
  if (type === 'kb') return item.kb_pending
  if (type === 'weekly') return item.weekly_reports_pending
  if (type === 'approvals') return item.approvals_pending
  return item.proposals_pending
}

export function ReviewQueueHome() {
  const [filter, setFilter] = useState<QueueFilter>('all')
  const { data, isLoading, isError } = useAdminReviewQueue()
  const activeTypes = ROLE_TYPES[filter]

  const rows = useMemo(() => {
    return (data ?? [])
      .map((item) => ({
        ...item,
        visible_pending: activeTypes.reduce((sum, type) => sum + countForType(item, type), 0),
      }))
      .filter((item) => item.visible_pending > 0)
      .sort(
        (a, b) =>
          b.visible_pending - a.visible_pending || a.tenant_name.localeCompare(b.tenant_name),
      )
  }, [activeTypes, data])

  const totals = activeTypes.reduce(
    (acc, type) => acc + (data ?? []).reduce((sum, item) => sum + countForType(item, type), 0),
    0,
  )

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-foreground">Review Queue</h1>
          <p className="mt-1 text-sm text-foreground-muted">
            Pendientes cross-tenant para operar KB, reportes, aprobaciones y propuestas.
          </p>
        </div>
        <div className="flex items-start gap-3">
          <div className="rounded-md bg-surface-muted px-3 py-2 text-right">
            <p className="text-xs text-foreground-muted">Pendientes visibles</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums text-foreground">
              {isLoading ? '...' : totals}
            </p>
          </div>
          <CreateTenantDialog />
        </div>
      </div>

      <Tabs value={filter} onValueChange={(value) => setFilter(value as QueueFilter)}>
        <TabsList className="w-full justify-start">
          {(Object.keys(FILTER_LABELS) as QueueFilter[]).map((key) => (
            <TabsTrigger key={key} value={key}>
              {FILTER_LABELS[key]}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {isError && (
        <div className="rounded-md bg-danger-subtle px-4 py-3 text-sm text-danger-foreground">
          No se pudo cargar la Review Queue.
        </div>
      )}

      {isLoading ? (
        <div className="grid gap-3">
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
        </div>
      ) : rows.length === 0 ? (
        <Card className="flex items-center justify-center gap-2 p-10 text-sm text-foreground-muted">
          <CheckCircle2 className="size-4 text-success-foreground" />
          Sin pendientes para este filtro.
        </Card>
      ) : (
        <div className="grid gap-3">
          {rows.map((item) => (
            <Card key={item.tenant_id} className="p-(--density-card-p)">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-sm font-semibold text-foreground">{item.tenant_name}</h2>
                    <Badge variant="secondary">{item.agent_lifecycle_state}</Badge>
                  </div>
                  <p className="mt-1 text-xs text-foreground-muted">{item.tenant_status}</p>
                </div>
                <Badge variant="warning">{item.visible_pending} pendientes</Badge>
              </div>

              <div className="mt-4 grid gap-2 md:grid-cols-4">
                {activeTypes.map((type) => {
                  const meta = TYPE_META[type]
                  const Icon = meta.icon
                  const count = countForType(item, type)
                  return (
                    <Link
                      key={type}
                      href={`/tenants/${item.tenant_id}/${meta.section}`}
                      className={cn(
                        'flex items-center justify-between gap-3 rounded-md border border-border-subtle px-3 py-2 transition-colors hover:bg-surface-muted',
                        count === 0 && 'opacity-45',
                      )}
                    >
                      <span className="flex min-w-0 items-center gap-2">
                        <Icon className="size-3.5 shrink-0 text-foreground-muted" />
                        <span className="truncate text-sm text-foreground-body">{meta.label}</span>
                      </span>
                      <span className="text-sm font-semibold tabular-nums text-foreground">
                        {count}
                      </span>
                    </Link>
                  )
                })}
              </div>
            </Card>
          ))}
        </div>
      )}

      <Button asChild variant="secondary" size="sm">
        <Link href="/dashboard">Actualizar cola</Link>
      </Button>
    </div>
  )
}
