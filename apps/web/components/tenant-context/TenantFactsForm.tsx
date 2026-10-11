'use client'

import { useEffect, useMemo, useState } from 'react'
import { CheckCircle2, Save, Store } from 'lucide-react'
import { useSaveTenantFacts, useTenantFacts } from '@/lib/api/hooks/tenant-context'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'

const STANDARD_FIELDS = [
  {
    key: 'business_hours',
    label: 'Horario de atención',
    placeholder: 'Lunes a viernes, 9:00-18:00',
    type: 'text',
    suffix: '',
  },
  {
    key: 'support_email',
    label: 'Email de soporte',
    placeholder: 'hola@tienda.com',
    type: 'email',
    suffix: '',
  },
  {
    key: 'support_phone',
    label: 'Teléfono de soporte',
    placeholder: '+34 910 123 456',
    type: 'tel',
    suffix: '',
  },
  {
    key: 'website_url',
    label: 'Web',
    placeholder: 'https://tienda.com',
    type: 'url',
    suffix: '',
  },
  {
    key: 'return_window_days',
    label: 'Ventana de devolución',
    placeholder: '30',
    type: 'number',
    suffix: 'días',
  },
  {
    key: 'return_policy_url',
    label: 'URL de devoluciones',
    placeholder: 'https://tienda.com/devoluciones',
    type: 'url',
    suffix: '',
  },
  {
    key: 'shipping_info',
    label: 'Información de envíos',
    placeholder: '24-48h hábiles en Península. Canarias 3-5 días.',
    type: 'text',
    suffix: '',
  },
  {
    key: 'email_signature',
    label: 'Firma de correo',
    placeholder: 'El equipo de Marea Studio\nhola@mareastudio.com',
    type: 'textarea',
    suffix: '',
  },
] as const

const FIELD_HELPERS: Partial<Record<string, string>> = {
  email_signature:
    'Se añade al final de las respuestas por correo. Si la dejas vacía, usamos "El equipo de" y el nombre de tu marca.',
}

type StandardKey = (typeof STANDARD_FIELDS)[number]['key']
type FactsFormState = Record<StandardKey, string>

const EMPTY_FORM: FactsFormState = {
  business_hours: '',
  support_email: '',
  support_phone: '',
  website_url: '',
  return_window_days: '',
  return_policy_url: '',
  shipping_info: '',
  email_signature: '',
}

function stringifyValue(value: unknown): string {
  if (value === null || value === undefined) return ''
  return String(value)
}

function pickCustomFacts(data: Record<string, unknown>) {
  const standard = new Set(STANDARD_FIELDS.map((field) => field.key))
  return Object.fromEntries(Object.entries(data).filter(([key]) => !standard.has(key as StandardKey)))
}

export function TenantFactsForm({ tenantId }: { tenantId: string }) {
  const [form, setForm] = useState<FactsFormState>(EMPTY_FORM)
  const [customJson, setCustomJson] = useState('{}')
  const [jsonError, setJsonError] = useState<string | null>(null)
  const [saveState, setSaveState] = useState<'idle' | 'saved' | 'error'>('idle')
  const { data, isLoading, isError } = useTenantFacts(tenantId)
  const saveMutation = useSaveTenantFacts(tenantId)

  useEffect(() => {
    if (!data) return
    setForm({
      business_hours: stringifyValue(data.data.business_hours),
      support_email: stringifyValue(data.data.support_email),
      support_phone: stringifyValue(data.data.support_phone),
      website_url: stringifyValue(data.data.website_url),
      return_window_days: stringifyValue(data.data.return_window_days),
      return_policy_url: stringifyValue(data.data.return_policy_url),
      shipping_info: stringifyValue(data.data.shipping_info),
      email_signature: stringifyValue(data.data.email_signature),
    })
    setCustomJson(JSON.stringify(pickCustomFacts(data.data), null, 2))
  }, [data])

  const completed = useMemo(
    () => STANDARD_FIELDS.filter((field) => form[field.key].trim().length > 0).length,
    [form],
  )

  async function save() {
    setJsonError(null)
    setSaveState('idle')

    let customFacts: Record<string, unknown>
    try {
      customFacts = JSON.parse(customJson || '{}') as Record<string, unknown>
      if (!customFacts || Array.isArray(customFacts) || typeof customFacts !== 'object') {
        throw new Error('El JSON extra debe ser un objeto.')
      }
    } catch (error) {
      setJsonError(error instanceof Error ? error.message : 'JSON inválido')
      return
    }

    const payload: Record<string, unknown> = { ...customFacts }
    for (const field of STANDARD_FIELDS) {
      const raw = form[field.key].trim()
      if (!raw) continue
      payload[field.key] =
        field.key === 'return_window_days' ? Number.parseInt(raw, 10) : raw
    }

    try {
      await saveMutation.mutateAsync(payload)
      setSaveState('saved')
    } catch {
      setSaveState('error')
    }
  }

  if (isLoading) {
    return <Skeleton className="h-[620px]" />
  }

  if (isError || !data) {
    return (
      <div className="rounded-md border border-danger bg-danger-subtle px-4 py-3 text-sm text-danger-foreground">
        No se pudieron cargar los datos del cliente.
      </div>
    )
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
      <Card className="p-(--density-card-p)">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <Store className="size-4 text-accent-foreground" />
              <h2 className="text-lg font-semibold text-foreground">Datos operativos</h2>
            </div>
            <p className="mt-1 max-w-2xl text-sm text-foreground-muted">
              Estos datos los puede mantener el cliente y el agente los lee sin esperar curación de Auyan.
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

        <div className="mt-6 grid gap-4 md:grid-cols-2">
          {STANDARD_FIELDS.map((field) => (
            <div
              key={field.key}
              className={
                field.key === 'shipping_info' || field.key === 'email_signature'
                  ? 'md:col-span-2'
                  : ''
              }
            >
              <Label htmlFor={field.key}>{field.label}</Label>
              <div className="mt-1.5 flex items-center gap-2">
                {field.type === 'textarea' ? (
                  <Textarea
                    id={field.key}
                    value={form[field.key]}
                    placeholder={field.placeholder}
                    rows={3}
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        [field.key]: event.target.value,
                      }))
                    }
                  />
                ) : (
                  <Input
                    id={field.key}
                    type={field.type ?? 'text'}
                    value={form[field.key]}
                    placeholder={field.placeholder}
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        [field.key]: event.target.value,
                      }))
                    }
                  />
                )}
                {field.suffix && (
                  <span className="shrink-0 text-sm text-foreground-muted">{field.suffix}</span>
                )}
              </div>
              {FIELD_HELPERS[field.key] && (
                <p className="mt-1.5 text-xs text-foreground-muted">{FIELD_HELPERS[field.key]}</p>
              )}
            </div>
          ))}
        </div>

        <div className="mt-6">
          <Label htmlFor="custom-facts">Campos extra en JSON</Label>
          <Textarea
            id="custom-facts"
            value={customJson}
            onChange={(event) => setCustomJson(event.target.value)}
            className="mt-1.5 min-h-32 font-mono text-xs"
          />
          {jsonError && <p className="mt-2 text-xs text-danger-foreground">{jsonError}</p>}
        </div>
      </Card>

      <Card className="h-fit p-(--density-card-p)">
        <div className="flex items-center justify-between">
          <p className="text-sm font-semibold text-foreground">Completitud</p>
          <CheckCircle2 className="size-4 text-success-foreground" />
        </div>
        <p className="mt-4 text-4xl font-semibold text-foreground">
          {completed}/{STANDARD_FIELDS.length}
        </p>
        <p className="mt-1 text-sm text-foreground-muted">campos estándar completos</p>
        <div className="mt-5 h-2 overflow-hidden rounded-full bg-surface-muted">
          <div
            className="h-full rounded-full bg-accent transition-all"
            style={{ width: `${(completed / STANDARD_FIELDS.length) * 100}%` }}
          />
        </div>
        <div className="mt-5 rounded-md border border-border-subtle bg-surface-muted px-4 py-3">
          <p className="text-xs font-medium uppercase tracking-wider text-foreground-muted">
            Impacto
          </p>
          <p className="mt-1 text-sm text-foreground-body">
            Cambios aquí afectan la siguiente respuesta del agente. Útil para horarios, teléfonos,
            enlaces y políticas factualizadas.
          </p>
        </div>
      </Card>
    </div>
  )
}
