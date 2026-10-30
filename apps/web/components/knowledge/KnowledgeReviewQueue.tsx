'use client'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import {
  type KnowledgeDocument,
  type TenantKnowledgeSubmission,
  useApproveTenantKnowledgeSubmission,
  useDeleteKnowledgeDocument,
  useKnowledgeDocuments,
  useRejectTenantKnowledgeSubmission,
  useTenantKnowledgeSubmissions,
} from '@/lib/api/hooks/tenant-context'
import { cn } from '@/lib/utils'
import { Check, FileText, Link2, Trash2, X } from 'lucide-react'
import { useMemo, useState } from 'react'

function sourceLabel(item: TenantKnowledgeSubmission) {
  return item.source_url || item.original_filename || item.source_type
}

function IndexedDocuments({ tenantId }: { tenantId: string }) {
  const { data, isLoading, isError } = useKnowledgeDocuments(tenantId)
  const deleteMutation = useDeleteKnowledgeDocument(tenantId)
  const [toDelete, setToDelete] = useState<KnowledgeDocument | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function confirmDelete() {
    if (!toDelete) return
    setError(null)
    try {
      await deleteMutation.mutateAsync(toDelete.id)
      setToDelete(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo borrar el documento')
    }
  }

  return (
    <Card className="p-(--density-card-p)">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-foreground">Documentos indexados</h2>
        <Badge variant="secondary">{data?.length ?? 0}</Badge>
      </div>
      {isLoading && <Skeleton className="mt-3 h-16" />}
      {isError && (
        <p className="mt-3 text-sm text-danger-foreground">
          No se pudieron cargar los documentos indexados.
        </p>
      )}
      {data?.length === 0 && (
        <p className="mt-3 text-sm text-foreground-muted">No hay documentos indexados.</p>
      )}
      <ul className="mt-3 divide-y divide-border-subtle">
        {(data ?? []).map((doc) => (
          <li key={doc.id} className="flex items-center justify-between gap-3 py-2">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-foreground">{doc.title}</p>
              <p className="truncate text-xs text-foreground-muted">
                {doc.source_key ?? doc.source ?? 'sin fuente'} · {doc.chunk_count} chunks
              </p>
            </div>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Borrar ${doc.title}`}
              onClick={() => {
                setError(null)
                setToDelete(doc)
              }}
            >
              <Trash2 className="size-4" />
            </Button>
          </li>
        ))}
      </ul>
      <Dialog open={toDelete !== null} onOpenChange={(open) => !open && setToDelete(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Borrar documento</DialogTitle>
            <DialogDescription>
              {toDelete?.title} dejará de salir en las respuestas del agente.
            </DialogDescription>
          </DialogHeader>
          {error && <p className="text-sm text-danger-foreground">{error}</p>}
          <DialogFooter>
            <Button variant="outline" onClick={() => setToDelete(null)}>
              Cancelar
            </Button>
            <Button
              variant="destructive"
              onClick={() => void confirmDelete()}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? 'Borrando' : 'Borrar'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  )
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
    <div className="grid gap-4">
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
                  <p className="truncate text-sm font-medium">
                    {item.title}
                    {item.metadata.duplicate_of ? (
                      <Badge variant="warning" className="ml-2">
                        Duplicado
                      </Badge>
                    ) : null}
                  </p>
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

              {typeof active.metadata.duplicate_of === 'string' && (
                <div className="mt-5 rounded-md border border-border bg-warning-subtle px-4 py-3">
                  <p className="text-sm text-foreground-body">
                    Mismo texto que{' '}
                    {active.metadata.duplicate_kind === 'submission'
                      ? 'otra fuente pendiente'
                      : 'un documento ya indexado'}{' '}
                    bajo otra clave ({active.metadata.duplicate_of}). Aprobarla dejaría el contenido
                    dos veces en la KB.
                  </p>
                </div>
              )}

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
      <IndexedDocuments tenantId={tenantId} />
    </div>
  )
}
