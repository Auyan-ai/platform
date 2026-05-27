'use client'

import { useEffect, useMemo, useState } from 'react'
import { BookOpenText, CheckCircle2, Save } from 'lucide-react'
import {
  type TenantPlaybookPayload,
  useSaveTenantPlaybook,
  useTenantPlaybook,
} from '@/lib/api/hooks/tenant-context'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'

const SECTIONS: Array<{
  key: keyof TenantPlaybookPayload
  title: string
  helper: string
  placeholder: string
}> = [
  {
    key: 'brand_voice',
    title: 'Voz de marca',
    helper: 'Tono, palabras prohibidas, nivel de cercanía y límites de promesa.',
    placeholder: 'Ej: Cercana, resolutiva y tranquila. No usar emojis. No prometer fechas exactas...',
  },
  {
    key: 'product_overview',
    title: 'Producto y propuesta',
    helper: 'Qué vende el cliente, para quién, qué lo diferencia.',
    placeholder: 'Ej: Marca de cosmética natural para piel sensible, ticket medio 45 euros...',
  },
  {
    key: 'policies',
    title: 'Políticas',
    helper: 'Envíos, cambios, devoluciones, garantías y condiciones comerciales.',
    placeholder: 'Ej: Devoluciones durante 30 días si el producto no fue abierto...',
  },
  {
    key: 'escalation_notes',
    title: 'Escalado',
    helper: 'Cuándo debe pasar a humano y con qué contexto.',
    placeholder: 'Ej: Escalar pedidos VIP, fraude, amenazas legales o importes mayores a 250 euros...',
  },
  {
    key: 'agent_instructions',
    title: 'Instrucciones del agente',
    helper: 'Reglas operativas explícitas que ganan sobre el AOP genérico.',
    placeholder: 'Ej: Si falta número de pedido, pedir email antes de escalar...',
  },
]

const EMPTY_FORM: TenantPlaybookPayload = {
  brand_voice: '',
  product_overview: '',
  policies: '',
  escalation_notes: '',
  agent_instructions: '',
}

function filledSections(form: TenantPlaybookPayload) {
  return SECTIONS.filter((section) => form[section.key].trim().length > 0).length
}

export function TenantPlaybookEditor({ tenantId }: { tenantId: string }) {
  const [form, setForm] = useState<TenantPlaybookPayload>(EMPTY_FORM)
  const [activeKey, setActiveKey] = useState<keyof TenantPlaybookPayload>('brand_voice')
  const [saveState, setSaveState] = useState<'idle' | 'saved' | 'error'>('idle')
  const { data, isLoading, isError } = useTenantPlaybook(tenantId)
  const saveMutation = useSaveTenantPlaybook(tenantId)

  useEffect(() => {
    if (!data) return
    setForm({
      brand_voice: data.brand_voice ?? '',
      product_overview: data.product_overview ?? '',
      policies: data.policies ?? '',
      escalation_notes: data.escalation_notes ?? '',
      agent_instructions: data.agent_instructions ?? '',
    })
  }, [data])

  const activeSection = useMemo(
    () => SECTIONS.find((section) => section.key === activeKey) ?? SECTIONS[0],
    [activeKey],
  )

  async function save() {
    setSaveState('idle')
    try {
      await saveMutation.mutateAsync(form)
      setSaveState('saved')
    } catch {
      setSaveState('error')
    }
  }

  if (isLoading) {
    return <Skeleton className="h-[520px]" />
  }

  if (isError || !data) {
    return (
      <div className="rounded-md border border-danger bg-danger-subtle px-4 py-3 text-sm text-danger-foreground">
        No se pudo cargar el playbook.
      </div>
    )
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
      <Card className="overflow-hidden p-2">
        <div className="border-b border-border-subtle px-3 py-3">
          <div className="flex items-center gap-2">
            <BookOpenText className="size-4 text-accent-foreground" />
            <p className="text-sm font-semibold text-foreground">Playbook</p>
          </div>
          <p className="mt-1 text-xs text-foreground-muted">
            {filledSections(form)} de {SECTIONS.length} secciones completas
          </p>
        </div>
        <nav className="space-y-1 p-2">
          {SECTIONS.map((section) => {
            const active = section.key === activeKey
            const complete = form[section.key].trim().length > 0
            return (
              <button
                key={section.key}
                type="button"
                onClick={() => setActiveKey(section.key)}
                className={cn(
                  'flex w-full items-center justify-between gap-3 rounded-sm px-3 py-2 text-left text-sm transition-colors',
                  active
                    ? 'bg-accent-subtle text-accent-foreground'
                    : 'text-foreground-body hover:bg-surface-muted hover:text-foreground',
                )}
              >
                <span>{section.title}</span>
                {complete && <CheckCircle2 className="size-3.5 text-success-foreground" />}
              </button>
            )
          })}
        </nav>
      </Card>

      <Card className="min-h-[520px] p-(--density-card-p)">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-semibold text-foreground">{activeSection.title}</h2>
              <Badge variant="outline">v{data.version}</Badge>
            </div>
            <p className="mt-1 max-w-2xl text-sm text-foreground-muted">
              {activeSection.helper}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {saveState === 'saved' && (
              <span className="text-xs text-success-foreground">Guardado</span>
            )}
            {saveState === 'error' && (
              <span className="text-xs text-danger-foreground">No se pudo guardar</span>
            )}
            <Button onClick={save} disabled={saveMutation.isPending}>
              <Save className="size-4" />
              {saveMutation.isPending ? 'Guardando' : 'Guardar'}
            </Button>
          </div>
        </div>

        <Textarea
          value={form[activeSection.key]}
          onChange={(event) =>
            setForm((current) => ({
              ...current,
              [activeSection.key]: event.target.value,
            }))
          }
          placeholder={activeSection.placeholder}
          className="mt-5 min-h-[340px] resize-y text-sm leading-6"
        />

        <div className="mt-4 rounded-md border border-border-subtle bg-surface-muted px-4 py-3">
          <p className="text-xs font-medium uppercase tracking-wider text-foreground-muted">
            Contexto para el agente
          </p>
          <p className="mt-1 text-sm text-foreground-body">
            Esta sección se inyecta en el system prompt como conocimiento fijo del cliente. No entra al RAG.
          </p>
        </div>
      </Card>
    </div>
  )
}
