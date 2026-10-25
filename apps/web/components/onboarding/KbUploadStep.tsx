'use client'

import { useState } from 'react'
import { FileText, Plus } from 'lucide-react'
import {
  useCreateTenantKnowledgeSubmission,
  useTenantKnowledgeSubmissions,
  type KnowledgeSourceType,
} from '@/lib/api/hooks/tenant-context'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'

const STATUS_VARIANT: Record<string, 'default' | 'success' | 'warning' | 'danger'> = {
  pending_review: 'warning',
  approved: 'success',
  rejected: 'danger',
}

const STATUS_LABEL: Record<string, string> = {
  pending_review: 'En revisión',
  approved: 'Aprobado',
  rejected: 'Rechazado',
}

export function KbUploadStep({ tenantId }: { tenantId: string }) {
  const submissionsQuery = useTenantKnowledgeSubmissions(tenantId)
  const createMutation = useCreateTenantKnowledgeSubmission(tenantId)

  const [title, setTitle] = useState('')
  const [sourceType, setSourceType] = useState<KnowledgeSourceType>('text')
  const [sourceUrl, setSourceUrl] = useState('')
  const [content, setContent] = useState('')
  const [notes, setNotes] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    setError(null)
    if (!title.trim()) {
      setError('Falta el título.')
      return
    }
    if (!content.trim() && !sourceUrl.trim()) {
      setError('Pega un texto o una URL con el contenido.')
      return
    }
    try {
      await createMutation.mutateAsync({
        title: title.trim(),
        source_type: sourceType,
        source_url: sourceUrl.trim() || null,
        original_filename: null,
        content: content.trim(),
        notes: notes.trim() || null,
      })
      setTitle('')
      setSourceUrl('')
      setContent('')
      setNotes('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo crear el envío.')
    }
  }

  return (
    <div className="grid gap-5">
      <p className="text-sm text-foreground-muted">
        Sube los documentos base de tu CX: políticas, FAQs, plantillas. Auyan revisa cada
        envío y lo indexa en la knowledge base del tenant. Para esta fase basta con un
        documento — luego puedes añadir más desde el dashboard.
      </p>

      <div className="grid gap-3">
        <div>
          <Label htmlFor="kb-title">Título</Label>
          <Input
            id="kb-title"
            value={title}
            placeholder="Política de devoluciones"
            onChange={(e) => setTitle(e.target.value)}
            className="mt-1.5"
          />
        </div>
        <div>
          <Label htmlFor="kb-type">Tipo de fuente</Label>
          <select
            id="kb-type"
            value={sourceType}
            onChange={(e) => setSourceType(e.target.value as KnowledgeSourceType)}
            className="mt-1.5 h-9 w-full rounded-sm border border-border bg-surface px-2 text-sm text-foreground"
          >
            <option value="text">Texto pegado</option>
            <option value="url">URL pública</option>
          </select>
        </div>
        {sourceType === 'url' && (
          <div>
            <Label htmlFor="kb-url">URL del recurso</Label>
            <Input
              id="kb-url"
              value={sourceUrl}
              placeholder="https://tienda.com/devoluciones"
              onChange={(e) => setSourceUrl(e.target.value)}
              className="mt-1.5"
            />
          </div>
        )}
        <div>
          <Label htmlFor="kb-content">Contenido</Label>
          <Textarea
            id="kb-content"
            value={content}
            placeholder="Pega aquí el texto completo del documento"
            onChange={(e) => setContent(e.target.value)}
            className="mt-1.5 min-h-40"
          />
        </div>
        <div>
          <Label htmlFor="kb-notes">Notas para el equipo Auyan (opcional)</Label>
          <Textarea
            id="kb-notes"
            value={notes}
            placeholder="Contexto, urgencia, dónde usarlo, etc."
            onChange={(e) => setNotes(e.target.value)}
            className="mt-1.5 min-h-20"
          />
        </div>
      </div>

      {error && <p className="text-sm text-danger-foreground">{error}</p>}

      <div>
        <Button onClick={submit} disabled={createMutation.isPending}>
          <Plus className="size-4" />
          {createMutation.isPending ? 'Enviando...' : 'Enviar para revisión'}
        </Button>
      </div>

      <div className="border-t border-border-subtle pt-4">
        <p className="mb-2 text-xs font-medium uppercase tracking-wider text-foreground-muted">
          Envíos
        </p>
        {submissionsQuery.isLoading ? (
          <Skeleton className="h-20 w-full" />
        ) : submissionsQuery.data && submissionsQuery.data.length > 0 ? (
          <ul className="space-y-2">
            {submissionsQuery.data.map((sub) => (
              <li
                key={sub.id}
                className="flex items-start justify-between gap-3 rounded-sm border border-border-subtle px-3 py-2 text-sm"
              >
                <div className="flex items-start gap-2">
                  <FileText className="mt-0.5 size-4 text-foreground-muted" />
                  <div>
                    <p className="font-medium text-foreground">{sub.title}</p>
                    <p className="text-xs text-foreground-muted">
                      {sub.source_type === 'url' ? sub.source_url : 'Texto pegado'}
                    </p>
                  </div>
                </div>
                <Badge variant={STATUS_VARIANT[sub.status] ?? 'secondary'}>
                  {STATUS_LABEL[sub.status] ?? sub.status}
                </Badge>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-foreground-muted">Aún no has subido nada.</p>
        )}
      </div>
    </div>
  )
}
