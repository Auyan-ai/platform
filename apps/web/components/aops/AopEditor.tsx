'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { useCreateAop, useSaveAop, useValidateAop, type AopWorkspace } from '@/lib/api/hooks/aops'
import { cn } from '@/lib/utils'

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
  /** Modo creación: no hay aopId */
  mode: 'create'
  initialWorkspace?: AopWorkspace
}

interface AopEditorEditProps {
  tenantId: string
  /** Modo edición: aopId requerido */
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
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          {props.mode === 'edit' ? (
            <>
              <h1 className="text-xl font-semibold text-neutral-900">{props.slug}</h1>
              <p className="text-xs text-neutral-400 mt-0.5">Versión actual: v{props.currentVersion}</p>
            </>
          ) : (
            <h1 className="text-xl font-semibold text-neutral-900">Nuevo AOP</h1>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleValidate}
            disabled={isLoading}
            className="rounded-lg border border-neutral-200 px-3 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-50 transition-colors"
          >
            Vista previa del prompt
          </button>
          <button
            onClick={handleSave}
            disabled={isLoading}
            className="rounded-lg bg-neutral-900 px-3 py-2 text-sm font-medium text-white hover:bg-neutral-700 disabled:opacity-50 transition-colors"
          >
            {isLoading
              ? 'Guardando...'
              : props.mode === 'create'
                ? 'Crear AOP'
                : 'Guardar versión'}
          </button>
        </div>
      </div>

      {/* Save error */}
      {saveError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {saveError.message}
        </div>
      )}

      {/* Success banner */}
      {saveMut?.isSuccess && (
        <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700">
          Nueva versión guardada correctamente.
        </div>
      )}

      {/* Editor + Preview split */}
      <div className={cn('flex gap-4', showPreview ? 'flex-row' : 'flex-col')}>
        {/* Raw source editor */}
        <div className={cn('flex flex-col', showPreview ? 'flex-1' : 'w-full')}>
          <label className="text-xs font-medium text-neutral-500 mb-1">
            Fuente del AOP (YAML frontmatter + Markdown)
          </label>
          <textarea
            value={source}
            onChange={(e) => setSource(e.target.value)}
            spellCheck={false}
            className={cn(
              'font-mono text-sm rounded-lg border border-neutral-200 bg-neutral-50 p-4',
              'focus:outline-none focus:ring-2 focus:ring-neutral-300 resize-none',
              showPreview ? 'h-[600px]' : 'h-[500px]',
            )}
          />
        </div>

        {/* Preview panel */}
        {showPreview && (
          <div className="flex-1 flex flex-col">
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs font-medium text-neutral-500">
                System prompt compilado
              </label>
              <button
                onClick={() => setShowPreview(false)}
                className="text-xs text-neutral-400 hover:text-neutral-600"
              >
                Cerrar
              </button>
            </div>
            {validateMut.isPending && (
              <div className="flex-1 flex items-center justify-center text-sm text-neutral-400 rounded-lg border border-neutral-200 bg-neutral-50">
                Compilando...
              </div>
            )}
            {previewErrors.length > 0 && (
              <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 space-y-1">
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
                  'flex-1 font-mono text-xs rounded-lg border border-neutral-200',
                  'bg-neutral-50 p-4 focus:outline-none resize-none h-[600px]',
                )}
              />
            )}
          </div>
        )}
      </div>

      {/* Help */}
      <p className="text-xs text-neutral-400">
        El AOP debe comenzar con un bloque <code className="bg-neutral-100 px-1 rounded">---</code>{' '}
        YAML que incluya al menos <code className="bg-neutral-100 px-1 rounded">slug</code> y{' '}
        <code className="bg-neutral-100 px-1 rounded">name</code>. Cada guardado crea una nueva
        versión inmutable.
      </p>
    </div>
  )
}
