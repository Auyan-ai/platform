'use client'

import { useState } from 'react'
import { CheckCircle2, FileText, Plus } from 'lucide-react'
import { WizardSplitLayout } from '../WizardLayouts'
import { WizardInput } from '../WizardInput'
import { WizardStepHeader } from '../WizardStepHeader'
import { WizardStepActions } from '../WizardStepActions'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
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

export function Step6Kb({ tenantId, onContinue, onSkip, onBack }: StepProps) {
  const submissionsQuery = useTenantKnowledgeSubmissions(tenantId)
  const createMutation = useCreateTenantKnowledgeSubmission(tenantId)

  const [title, setTitle] = useState('')
  const [sourceType, setSourceType] = useState<KnowledgeSourceType>('text')
  const [sourceUrl, setSourceUrl] = useState('')
  const [content, setContent] = useState('')
  const [error, setError] = useState<string | null>(null)

  const hasSubmissions = (submissionsQuery.data?.length ?? 0) > 0

  /** Devuelve true si el envío se guardó (o no había nada que enviar). False = bloqueo. */
  async function submitCurrent(): Promise<boolean> {
    setError(null)
    const hasAnyInput = title.trim() || content.trim() || sourceUrl.trim()
    if (!hasAnyInput) return true // nada que enviar, no es error
    if (!title.trim()) {
      setError('Falta el título del documento.')
      return false
    }
    if (!content.trim() && !sourceUrl.trim()) {
      setError('Pega el texto del documento o una URL.')
      return false
    }
    try {
      await createMutation.mutateAsync({
        title: title.trim(),
        source_type: sourceType,
        source_url: sourceUrl.trim() || null,
        original_filename: null,
        content: content.trim(),
        notes: null,
      })
      setTitle('')
      setSourceUrl('')
      setContent('')
      return true
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo crear el envío.')
      return false
    }
  }

  /** Click directo en el botón "Enviar documento". */
  async function handleSubmitDocument() {
    // submitCurrent ya valida que hay título + contenido. Si no, error visible.
    if (!title.trim() && !content.trim() && !sourceUrl.trim()) {
      setError('Llena al menos título + contenido.')
      return
    }
    await submitCurrent()
  }

  /** Click en "Continuar": si hay datos sin enviar, los manda primero, luego avanza. */
  async function handleContinue() {
    const ok = await submitCurrent()
    if (!ok) return
    onContinue()
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

      <div className="mt-4 flex items-center justify-end">
        <Button
          variant={hasSubmissions ? 'ghost' : 'primary'}
          size="sm"
          onClick={handleSubmitDocument}
          disabled={createMutation.isPending}
        >
          <Plus className="size-4" />
          {createMutation.isPending
            ? 'Enviando...'
            : hasSubmissions
              ? 'Añadir otro documento'
              : 'Enviar documento'}
        </Button>
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
        onContinue={handleContinue}
        onBack={onBack}
        onSkip={hasSubmissions ? undefined : onSkip}
        continueLabel="Continuar"
        continueLoading={createMutation.isPending}
      />
    </WizardSplitLayout>
  )
}
