'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { useCreateAop, useSaveAop, useValidateAop, type AopWorkspace } from '@/lib/api/hooks/aops'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'

const DEFAULT_TEMPLATE = `---
name: Nombre del AOP
slug: nombre_del_aop
workspace: production
allowed_skills: []
required_data: []
guardrails:
  - Nunca inventes información que no tengas en la KB.
max_tool_iterations: 5
confidence_threshold: 0.70
require_supervision: false
escalation_triggers:
  - El cliente está muy frustrado
  - No tengo información suficiente para resolver
triggers:
  description: Descripción breve del intent que activa este AOP
---

## Procedimiento

Describe aquí cómo debe comportarse el agente cuando se activa este AOP.

1. Paso uno
2. Paso dos
3. Paso tres
`

interface AopEditorProps {
  tenantId: string
  mode: 'create'
  initialWorkspace?: AopWorkspace
}

interface AopEditorEditProps {
  tenantId: string
  mode: 'edit'
  aopId: string
  initialSource: string
  currentVersion: number
  slug: string
}

type Props = AopEditorProps | AopEditorEditProps

export function AopEditor(props: Props) {
  const router = useRouter()
  const { tenantId } = props

  const [source, setSource] = useState(
    props.mode === 'edit' ? props.initialSource : DEFAULT_TEMPLATE,
  )
  const [workspace] = useState<AopWorkspace>(
    props.mode === 'edit'
      ? (props.initialSource.match(/workspace:\s*(\w+)/)?.[1] as AopWorkspace) ?? 'production'
      : props.mode === 'create'
        ? (props.initialWorkspace ?? 'production')
        : 'production',
  )
  const [previewPrompt, setPreviewPrompt] = useState<string | null>(null)
  const [previewErrors, setPreviewErrors] = useState<string[]>([])
  const [showPreview, setShowPreview] = useState(false)

  const createMut = useCreateAop(tenantId)
  const saveMut = props.mode === 'edit' ? useSaveAop(tenantId, props.aopId) : null
  const validateMut = useValidateAop(tenantId)

  const isLoading =
    createMut.isPending || (saveMut?.isPending ?? false) || validateMut.isPending

  async function handleSave() {
    if (props.mode === 'create') {
      const result = await createMut.mutateAsync({ raw_source: source, workspace })
      router.push(`/tenants/${tenantId}/aops/${result.id}`)
    } else {
      await saveMut!.mutateAsync({ raw_source: source })
    }
  }

  async function handleValidate() {
    setShowPreview(true)
    setPreviewPrompt(null)
    setPreviewErrors([])
    const result = await validateMut.mutateAsync({ raw_source: source, workspace })
    if (result.valid && result.system_prompt) {
      setPreviewPrompt(result.system_prompt)
    } else {
      setPreviewErrors(result.errors)
    }
  }

  const saveError = createMut.error ?? saveMut?.error ?? null

  return (
    <div className="flex flex-col gap-4 h-full">
      <div className="flex items-center justify-between">
        <div>
          {props.mode === 'edit' ? (
            <>
              <h1 className="text-xl font-semibold text-foreground font-mono">{props.slug}</h1>
              <p className="text-xs text-foreground-muted mt-0.5 tabular-nums">
                Versión actual: v{props.currentVersion}
              </p>
            </>
          ) : (
            <h1 className="text-xl font-semibold text-foreground">Nuevo AOP</h1>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={handleValidate} disabled={isLoading}>
            Vista previa del prompt
          </Button>
          <Button size="sm" onClick={handleSave} disabled={isLoading}>
            {isLoading
              ? 'Guardando…'
              : props.mode === 'create'
                ? 'Crear AOP'
                : 'Guardar versión'}
          </Button>
        </div>
      </div>

      {saveError && (
        <div className="rounded-md bg-danger-subtle px-4 py-3 text-sm text-danger-foreground">
          {saveError.message}
        </div>
      )}

      {saveMut?.isSuccess && (
        <div className="rounded-md bg-success-subtle px-4 py-3 text-sm text-success-foreground">
          Nueva versión guardada correctamente.
        </div>
      )}

      <div className={cn('flex gap-4', showPreview ? 'flex-row' : 'flex-col')}>
        <div className={cn('flex flex-col', showPreview ? 'flex-1' : 'w-full')}>
          <Label className="mb-1">Fuente del AOP (YAML frontmatter + Markdown)</Label>
          <textarea
            value={source}
            onChange={(e) => setSource(e.target.value)}
            spellCheck={false}
            className={cn(
              'font-mono text-sm rounded-md border border-border bg-surface-muted p-4 text-foreground',
              'hover:border-border-strong transition-colors resize-none',
              showPreview ? 'h-[600px]' : 'h-[500px]',
            )}
          />
        </div>

        {showPreview && (
          <div className="flex-1 flex flex-col">
            <div className="flex items-center justify-between mb-1">
              <Label>System prompt compilado</Label>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setShowPreview(false)}
                className="h-6 text-xs"
              >
                Cerrar
              </Button>
            </div>
            {validateMut.isPending && (
              <div className="flex-1 flex items-center justify-center text-sm text-foreground-muted rounded-md border border-border bg-surface-muted">
                Compilando…
              </div>
            )}
            {previewErrors.length > 0 && (
              <div className="rounded-md bg-danger-subtle p-4 text-sm text-danger-foreground space-y-1">
                <p className="font-medium">Errores de validación:</p>
                {previewErrors.map((e, i) => (
                  <p key={i}>• {e}</p>
                ))}
              </div>
            )}
            {previewPrompt && (
              <textarea
                readOnly
                value={previewPrompt}
                className={cn(
                  'flex-1 font-mono text-xs rounded-md border border-border',
                  'bg-surface-muted p-4 resize-none h-[600px] text-foreground-body',
                )}
              />
            )}
          </div>
        )}
      </div>

      <p className="text-xs text-foreground-muted">
        El AOP debe comenzar con un bloque{' '}
        <code className="bg-surface-muted px-1 rounded-xs font-mono">---</code> YAML que incluya al
        menos <code className="bg-surface-muted px-1 rounded-xs font-mono">slug</code> y{' '}
        <code className="bg-surface-muted px-1 rounded-xs font-mono">name</code>. Cada guardado
        crea una nueva versión inmutable.
      </p>
    </div>
  )
}
