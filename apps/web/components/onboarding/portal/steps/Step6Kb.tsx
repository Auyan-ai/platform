'use client'

import { useState } from 'react'
import { CheckCircle2, FileText } from 'lucide-react'
import { WizardSplitLayout } from '../WizardLayouts'
import { WizardInput } from '../WizardInput'
import { WizardStepHeader } from '../WizardStepHeader'
import { WizardStepActions } from '../WizardStepActions'
import { Badge } from '@/components/ui/badge'
import { Textarea } from '@/components/ui/textarea'
import {
  useCreateTenantKnowledgeSubmission,
  useTenantKnowledgeSubmissions,
  type KnowledgeSourceType,
} from '@/lib/api/hooks/tenant-context'
import type { StepProps } from './types'

const STATUS_VARIANT: Record<string, 'default' | 'success' | 'warning' | 'danger'> = {
  pending_review: 'warning',
  approved: 'success',
  rejected: 'danger',
}

export function Step6Kb({ tenantId, onContinue, onSkip }: StepProps) {
  const submissionsQuery = useTenantKnowledgeSubmissions(tenantId)
  const createMutation = useCreateTenantKnowledgeSubmission(tenantId)

  const [title, setTitle] = useState('')
  const [sourceType, setSourceType] = useState<KnowledgeSourceType>('text')
  const [sourceUrl, setSourceUrl] = useState('')
  const [content, setContent] = useState('')
  const [error, setError] = useState<string | null>(null)

  const hasSubmissions = (submissionsQuery.data?.length ?? 0) > 0

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
        content: content.trim() || sourceUrl.trim(),
        notes: null,
      })
      setTitle('')
      setSourceUrl('')
      setContent('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo crear el envío.')
    }
  }

  return (
    <WizardSplitLayout>
      <WizardStepHeader
        title="Knowledge base inicial"
        subtitle="Sube tu política de devoluciones, FAQ o documentos clave. Auyan los revisa y los indexa."
      />

      {hasSubmissions && (
        <div className="mb-5 flex items-start gap-2 rounded-md border border-success bg-success-subtle px-3 py-2 text-sm text-success-foreground">
          <CheckCircle2 className="size-4 shrink-0" />
          <div>
            <p className="font-medium">{submissionsQuery.data?.length} documento(s) en revisión</p>
            <p className="text-xs opacity-80">Puedes añadir más o continuar.</p>
          </div>
        </div>
      )}

      <div className="grid gap-3">
        <WizardInput
          label="Título"
          placeholder="Política de devoluciones"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <div>
          <label
            htmlFor="kb-type"
            className="mb-1.5 block text-xs font-normal text-foreground-muted"
          >
            Tipo de fuente
          </label>
          <select
            id="kb-type"
            value={sourceType}
            onChange={(e) => setSourceType(e.target.value as KnowledgeSourceType)}
            className="flex h-9 w-full appearance-none rounded-sm border border-transparent bg-surface-muted bg-no-repeat px-3 pr-9 text-sm text-foreground transition-colors hover:bg-[#EEECEA] focus:bg-surface focus:border-accent focus:outline focus:outline-2 focus:outline-accent focus:outline-offset-2"
            style={{
              backgroundImage:
                "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2378716C' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'></polyline></svg>\")",
              backgroundPosition: 'right 12px center',
            }}
          >
            <option value="text">Texto pegado</option>
            <option value="url">URL pública</option>
          </select>
        </div>
        {sourceType === 'url' && (
          <WizardInput
            label="URL del recurso"
            placeholder="https://tienda.com/devoluciones"
            value={sourceUrl}
            onChange={(e) => setSourceUrl(e.target.value)}
          />
        )}
        <div>
          <label
            htmlFor="kb-content"
            className="mb-1.5 block text-xs font-normal text-foreground-muted"
          >
            Contenido
          </label>
          <Textarea
            id="kb-content"
            placeholder="Pega aquí el texto completo del documento."
            value={content}
            onChange={(e) => setContent(e.target.value)}
            className="min-h-32 border-transparent bg-surface-muted text-sm hover:bg-[#EEECEA] focus-visible:bg-surface focus-visible:border-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2"
          />
        </div>
      </div>

      {error && <p className="mt-3 text-sm text-danger-foreground">{error}</p>}

      <div className="mt-4 flex items-center justify-end gap-3">
        <button
          type="button"
          onClick={submit}
          disabled={createMutation.isPending}
          className="rounded-sm px-2 py-1.5 text-xs text-foreground-muted transition-colors hover:bg-surface-muted hover:text-foreground-body disabled:opacity-50"
        >
          {createMutation.isPending ? 'Enviando...' : '+ Añadir otro documento'}
        </button>
      </div>

      {hasSubmissions && (
        <div className="mt-5 border-t border-border-subtle pt-4">
          <p className="mb-2 text-xs font-medium uppercase tracking-wider text-foreground-muted">
            Envíos
          </p>
          <ul className="space-y-2">
            {submissionsQuery.data?.map((sub) => (
              <li
                key={sub.id}
                className="flex items-start justify-between gap-3 rounded-sm bg-surface-muted px-3 py-2 text-sm"
              >
                <div className="flex items-start gap-2">
                  <FileText className="mt-0.5 size-4 text-foreground-muted" />
                  <span className="font-medium text-foreground">{sub.title}</span>
                </div>
                <Badge variant={STATUS_VARIANT[sub.status] ?? 'secondary'}>{sub.status}</Badge>
              </li>
            ))}
          </ul>
        </div>
      )}

      <WizardStepActions
        onContinue={onContinue}
        onSkip={hasSubmissions ? undefined : onSkip}
        continueLabel="Continuar"
        continueDisabled={!hasSubmissions && createMutation.isPending}
      />
    </WizardSplitLayout>
  )
}
