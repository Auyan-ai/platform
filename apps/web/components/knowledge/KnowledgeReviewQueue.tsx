'use client'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import {
  type TenantKnowledgeSubmission,
  useApproveTenantKnowledgeSubmission,
  useRejectTenantKnowledgeSubmission,
  useTenantKnowledgeSubmissions,
} from '@/lib/api/hooks/tenant-context'
import { cn } from '@/lib/utils'
import { Check, FileText, Link2, X } from 'lucide-react'
import { useMemo, useState } from 'react'

function sourceLabel(item: TenantKnowledgeSubmission) {
  return item.source_url || item.original_filename || item.source_type
}

export function KnowledgeReviewQueue({ tenantId }: { tenantId: string }) {
  const [activeId, setActiveId] = useState<string | null>(null)
  const [reviewNote, setReviewNote] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const { data, isLoading, isError } = useTenantKnowledgeSubmissions(tenantId, 'pending_review')
  const approveMutation = useApproveTenantKnowledgeSubmission(tenantId)
  const rejectMutation = useRejectTenantKnowledgeSubmission(tenantId)

  const active = useMemo(() => {
    if (!data?.length) return null
    return data.find((item) => item.id === activeId) ?? data[0]
  }, [activeId, data])

  async function approve() {
    if (!active) return
    setMessage(null)
    try {
      await approveMutation.mutateAsync({
        submissionId: active.id,
        reviewNote: reviewNote.trim() || undefined,
      })
      setReviewNote('')
      setActiveId(null)
      setMessage('Indexado en KB')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'No se pudo aprobar')
    }
  }

  async function reject() {
    if (!active) return
    setMessage(null)
    try {
      await rejectMutation.mutateAsync({
        submissionId: active.id,
        reviewNote: reviewNote.trim() || undefined,
      })
      setReviewNote('')
      setActiveId(null)
      setMessage('Rechazado')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'No se pudo rechazar')
    }
  }

  if (isLoading) {
    return <Skeleton className="h-[620px]" />
  }

  if (isError) {
    return (
      <div className="rounded-md border border-danger bg-danger-subtle px-4 py-3 text-sm text-danger-foreground">
        No se pudo cargar la cola de conocimiento.
      </div>
    )
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
      <Card className="overflow-hidden p-2">
        <div className="border-b border-border-subtle px-3 py-3">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <FileText className="size-4 text-accent-foreground" />
              <p className="text-sm font-semibold text-foreground">Pending review</p>
            </div>
            <Badge variant={(data?.length ?? 0) > 0 ? 'warning' : 'secondary'}>
              {data?.length ?? 0}
            </Badge>
          </div>
        </div>

        <nav className="max-h-[560px] space-y-1 overflow-y-auto p-2">
          {(data ?? []).map((item) => {
            const isActive = active?.id === item.id
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => {
                  setActiveId(item.id)
                  setReviewNote('')
                  setMessage(null)
                }}
                className={cn(
                  'w-full rounded-sm px-3 py-2 text-left transition-colors',
                  isActive ? 'bg-accent-subtle text-accent-foreground' : 'hover:bg-surface-muted',
                )}
              >
                <p className="truncate text-sm font-medium">{item.title}</p>
                <p className="mt-1 truncate text-xs text-foreground-muted">{sourceLabel(item)}</p>
              </button>
            )
          })}
          {data?.length === 0 && (
            <p className="px-3 py-4 text-sm text-foreground-muted">No hay contenido pendiente.</p>
          )}
        </nav>
      </Card>

      <Card className="min-h-[620px] p-(--density-card-p)">
        {active ? (
          <>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-lg font-semibold text-foreground">{active.title}</h2>
                  <Badge variant="warning">Pendiente</Badge>
                </div>
                <div className="mt-2 flex items-center gap-1.5 text-sm text-foreground-muted">
                  <Link2 className="size-3.5" />
                  <span className="break-all">{sourceLabel(active)}</span>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  onClick={() => void reject()}
                  disabled={rejectMutation.isPending || approveMutation.isPending}
                >
                  <X className="size-4" />
                  Rechazar
                </Button>
                <Button
                  onClick={() => void approve()}
                  disabled={rejectMutation.isPending || approveMutation.isPending}
                >
                  <Check className="size-4" />
                  {approveMutation.isPending ? 'Indexando' : 'Aprobar'}
                </Button>
              </div>
            </div>

            {active.notes && (
              <div className="mt-5 rounded-md border border-border-subtle bg-surface-muted px-4 py-3">
                <p className="text-xs font-medium uppercase tracking-wider text-foreground-muted">
                  Nota cliente
                </p>
                <p className="mt-1 text-sm text-foreground-body">{active.notes}</p>
              </div>
            )}

            <pre className="mt-5 max-h-[300px] overflow-auto whitespace-pre-wrap rounded-md border border-border-subtle bg-surface-muted p-4 text-sm leading-6 text-foreground-body">
              {active.content || 'Sin contenido pegado. Revisar URL de origen antes de aprobar.'}
            </pre>

            <div className="mt-5">
              <Textarea
                value={reviewNote}
                onChange={(event) => setReviewNote(event.target.value)}
                placeholder="Nota interna de revisión"
                className="min-h-24"
              />
            </div>

            {message && <p className="mt-3 text-sm text-foreground-muted">{message}</p>}
          </>
        ) : (
          <div className="flex min-h-[500px] items-center justify-center text-sm text-foreground-muted">
            Cola vacía.
          </div>
        )}
      </Card>
    </div>
  )
}
