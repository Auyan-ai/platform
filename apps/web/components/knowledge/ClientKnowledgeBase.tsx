'use client'

import { KnowledgeDropZone } from '@/components/knowledge/KnowledgeDropZone'
import { TenantFactsForm } from '@/components/tenant-context/TenantFactsForm'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  type KnowledgeSubmissionStatus,
  useTenantKnowledgeSubmissions,
} from '@/lib/api/hooks/tenant-context'
import { CheckCircle2, Clock3, Database, FileText, XCircle } from 'lucide-react'

const STATUS_LABELS: Record<KnowledgeSubmissionStatus, string> = {
  pending_review: 'En revisión',
  approved: 'Procesado',
  rejected: 'Rechazado',
  superseded: 'Sustituido',
}

const STATUS_ICON = {
  pending_review: Clock3,
  approved: CheckCircle2,
  rejected: XCircle,
  superseded: XCircle,
} satisfies Record<KnowledgeSubmissionStatus, typeof Clock3>

function StatusCard({
  status,
  count,
}: {
  status: KnowledgeSubmissionStatus
  count: number
}) {
  const Icon = STATUS_ICON[status]
  return (
    <Card className="p-(--density-card-p)">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-foreground">{STATUS_LABELS[status]}</p>
          <p className="mt-2 text-2xl font-semibold tabular-nums text-foreground">{count}</p>
        </div>
        <div className="grid size-8 place-items-center rounded-md bg-surface-muted">
          <Icon className="size-4 text-foreground-muted" />
        </div>
      </div>
    </Card>
  )
}

export function ClientKnowledgeBase({ tenantId }: { tenantId: string }) {
  const { data, isLoading, isError } = useTenantKnowledgeSubmissions(tenantId)
  const submissions = data ?? []
  const pending = submissions.filter((item) => item.status === 'pending_review').length
  const approved = submissions.filter((item) => item.status === 'approved').length
  const rejected = submissions.filter((item) => item.status === 'rejected').length
  const latest = submissions.slice(0, 5)

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-3">
        {isLoading ? (
          <>
            <Skeleton className="h-28" />
            <Skeleton className="h-28" />
            <Skeleton className="h-28" />
          </>
        ) : (
          <>
            <StatusCard status="pending_review" count={pending} />
            <StatusCard status="approved" count={approved} />
            <StatusCard status="rejected" count={rejected} />
          </>
        )}
      </div>

      {isError && (
        <div className="rounded-md bg-danger-subtle px-4 py-3 text-sm text-danger-foreground">
          No se pudo cargar el estado de procesamiento.
        </div>
      )}

      <Tabs defaultValue="dropzone">
        <TabsList className="w-full justify-start">
          <TabsTrigger value="dropzone">
            <FileText className="size-3.5" />
            Contenido
          </TabsTrigger>
          <TabsTrigger value="facts">
            <Database className="size-3.5" />
            Datos factuales
          </TabsTrigger>
        </TabsList>

        <TabsContent value="dropzone" className="mt-4 space-y-4">
          <KnowledgeDropZone tenantId={tenantId} />

          <Card className="p-(--density-card-p)">
            <div className="mb-4 flex items-center justify-between gap-3">
              <h2 className="text-sm font-semibold text-foreground">Últimos envíos</h2>
              <Badge variant={pending > 0 ? 'warning' : 'muted'}>{pending} pendientes</Badge>
            </div>
            {latest.length > 0 ? (
              <div className="divide-y divide-border-subtle">
                {latest.map((item) => (
                  <div key={item.id} className="flex items-center gap-3 py-3">
                    <Badge
                      variant={
                        item.status === 'approved'
                          ? 'success'
                          : item.status === 'rejected'
                            ? 'danger'
                            : 'warning'
                      }
                    >
                      {STATUS_LABELS[item.status]}
                    </Badge>
                    <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground-body">
                      {item.title}
                    </span>
                    <span className="text-xs text-foreground-muted">{item.source_type}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="py-6 text-center text-sm text-foreground-muted">
                Aún no hay contenido enviado.
              </p>
            )}
          </Card>
        </TabsContent>

        <TabsContent value="facts" className="mt-4">
          <TenantFactsForm tenantId={tenantId} />
        </TabsContent>
      </Tabs>
    </div>
  )
}
