'use client'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import {
  type KnowledgeSourceType,
  useCreateTenantKnowledgeSubmission,
  useTenantKnowledgeSubmissions,
} from '@/lib/api/hooks/tenant-context'
import { FileText, Link2, Save, Upload } from 'lucide-react'
import { useMemo, useRef, useState } from 'react'

interface FormState {
  title: string
  sourceType: KnowledgeSourceType
  sourceUrl: string
  originalFilename: string
  content: string
  notes: string
}

const EMPTY_FORM: FormState = {
  title: '',
  sourceType: 'text',
  sourceUrl: '',
  originalFilename: '',
  content: '',
  notes: '',
}

function statusLabel(status: string) {
  if (status === 'approved') return 'Aprobado'
  if (status === 'rejected') return 'Rechazado'
  return 'Pendiente'
}

export function KnowledgeDropZone({ tenantId }: { tenantId: string }) {
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [message, setMessage] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const { data, isLoading } = useTenantKnowledgeSubmissions(tenantId)
  const createMutation = useCreateTenantKnowledgeSubmission(tenantId)

  const pendingCount = useMemo(
    () => data?.filter((item) => item.status === 'pending_review').length ?? 0,
    [data],
  )

  async function handleFiles(files: FileList | null) {
    const file = files?.[0]
    if (!file) return
    const text = await file.text()
    setForm((current) => ({
      ...current,
      title: current.title || file.name.replace(/\.[^.]+$/, ''),
      sourceType: 'file',
      originalFilename: file.name,
      content: text,
    }))
    setMessage(`Archivo cargado: ${file.name}`)
  }

  async function submit() {
    setMessage(null)
    try {
      await createMutation.mutateAsync({
        title: form.title.trim(),
        source_type: form.sourceType,
        source_url: form.sourceUrl.trim() || null,
        original_filename: form.originalFilename || null,
        content: form.content.trim(),
        notes: form.notes.trim() || null,
        metadata: { intake: 'client_drop_zone' },
      })
      setForm(EMPTY_FORM)
      if (fileInputRef.current) fileInputRef.current.value = ''
      setMessage('Enviado a revisión')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'No se pudo enviar')
    }
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
      <Card className="p-(--density-card-p)">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <Upload className="size-4 text-accent-foreground" />
              <h2 className="text-lg font-semibold text-foreground">Aportar conocimiento</h2>
            </div>
            <p className="mt-1 max-w-2xl text-sm text-foreground-muted">
              Políticas, FAQs, guías de envío, garantías o respuestas frecuentes.
            </p>
          </div>
          <Button
            onClick={submit}
            disabled={
              createMutation.isPending ||
              !form.title.trim() ||
              (!form.content.trim() && !form.sourceUrl)
            }
          >
            <Save className="size-4" />
            {createMutation.isPending ? 'Enviando' : 'Enviar'}
          </Button>
        </div>

        <div className="mt-6 grid gap-4 md:grid-cols-2">
          <div>
            <Label htmlFor="kb-title">Título</Label>
            <Input
              id="kb-title"
              value={form.title}
              onChange={(event) =>
                setForm((current) => ({ ...current, title: event.target.value }))
              }
              placeholder="Política de devoluciones"
              className="mt-1.5"
            />
          </div>
          <div>
            <Label htmlFor="kb-url">URL de origen</Label>
            <Input
              id="kb-url"
              value={form.sourceUrl}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  sourceType: event.target.value ? 'url' : current.sourceType,
                  sourceUrl: event.target.value,
                }))
              }
              placeholder="https://tienda.com/devoluciones"
              className="mt-1.5"
            />
          </div>
        </div>

        <div
          className="mt-5 rounded-md border border-dashed border-border bg-surface-muted px-4 py-5"
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault()
            void handleFiles(event.dataTransfer.files)
          }}
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <FileText className="size-5 text-foreground-muted" />
              <div>
                <p className="text-sm font-medium text-foreground">Archivo de texto o markdown</p>
                <p className="text-xs text-foreground-muted">
                  {form.originalFilename || 'Arrastra un archivo o selecciónalo.'}
                </p>
              </div>
            </div>
            <Button variant="outline" onClick={() => fileInputRef.current?.click()}>
              <Upload className="size-4" />
              Seleccionar
            </Button>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept=".txt,.md,.markdown,.csv,.html"
            className="hidden"
            onChange={(event) => void handleFiles(event.target.files)}
          />
        </div>

        <div className="mt-5">
          <Label htmlFor="kb-content">Contenido</Label>
          <Textarea
            id="kb-content"
            value={form.content}
            onChange={(event) =>
              setForm((current) => ({
                ...current,
                sourceType:
                  current.sourceType === 'file' ? 'file' : current.sourceUrl ? 'url' : 'text',
                content: event.target.value,
              }))
            }
            placeholder="Pega aquí el contenido que Auyan debe revisar."
            className="mt-1.5 min-h-52"
          />
        </div>

        <div className="mt-5">
          <Label htmlFor="kb-notes">Notas para Auyan</Label>
          <Textarea
            id="kb-notes"
            value={form.notes}
            onChange={(event) => setForm((current) => ({ ...current, notes: event.target.value }))}
            placeholder="Qué cambió, qué hay que revisar o qué prioridad tiene."
            className="mt-1.5 min-h-24"
          />
        </div>

        {message && <p className="mt-3 text-sm text-foreground-muted">{message}</p>}
      </Card>

      <Card className="h-fit p-(--density-card-p)">
        <div className="flex items-center justify-between">
          <p className="text-sm font-semibold text-foreground">Cola</p>
          <Badge variant={pendingCount > 0 ? 'warning' : 'secondary'}>
            {pendingCount} pendientes
          </Badge>
        </div>
        {isLoading ? (
          <Skeleton className="mt-5 h-48" />
        ) : (
          <div className="mt-5 space-y-3">
            {(data ?? []).slice(0, 6).map((item) => (
              <div key={item.id} className="rounded-md border border-border-subtle px-3 py-2">
                <div className="flex items-start justify-between gap-2">
                  <p className="min-w-0 truncate text-sm font-medium text-foreground">
                    {item.title}
                  </p>
                  <Badge
                    variant={
                      item.status === 'approved'
                        ? 'success'
                        : item.status === 'rejected'
                          ? 'danger'
                          : 'warning'
                    }
                  >
                    {statusLabel(item.status)}
                  </Badge>
                </div>
                <div className="mt-2 flex items-center gap-1.5 text-xs text-foreground-muted">
                  <Link2 className="size-3" />
                  <span className="truncate">
                    {item.source_url || item.original_filename || item.source_type}
                  </span>
                </div>
              </div>
            ))}
            {data?.length === 0 && (
              <p className="text-sm text-foreground-muted">No hay contenidos enviados.</p>
            )}
          </div>
        )}
      </Card>
    </div>
  )
}
