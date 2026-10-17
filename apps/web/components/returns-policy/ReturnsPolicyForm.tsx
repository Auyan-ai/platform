'use client'

import { AlertTriangle, History, Plus, Save, Trash2 } from 'lucide-react'
import { type ReactNode, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { useReturnsPolicy, useSaveReturnsPolicy } from '@/lib/api/hooks/returns-policy'
import { ApiError } from '@/lib/api/hooks/tenant-context'
import {
  type ExchangeKind,
  type FieldErrors,
  type PolicyForm,
  type ReasonRow,
  MAX_REASONS,
  SHOPIFY_REASONS,
  allMessages,
  emptyReason,
  fieldErrorsFrom422,
  fromPolicy,
  slugifyCode,
  toPayload,
} from '@/lib/returns-policy'

const SELECT_CLASS =
  'flex h-9 w-full rounded-sm border border-border bg-surface px-3 py-1 text-sm text-foreground transition-colors hover:border-border-strong aria-invalid:border-danger'

const SHOPIFY_REASON_LABELS: Record<(typeof SHOPIFY_REASONS)[number], string> = {
  'damaged-or-defective': 'Dañado o defectuoso',
  'received-the-wrong-item': 'Recibió un artículo equivocado',
  'item-not-as-described': 'No es como se describía',
  'too-small': 'Demasiado pequeño',
  'too-big': 'Demasiado grande',
  style: 'Estilo',
  color: 'Color',
  'changed-my-mind': 'Cambió de opinión',
  'other-reason': 'Otro motivo',
}

interface Option<T extends string> {
  value: T
  label: string
  hint?: string
}

function RadioGroup<T extends string>({
  name,
  value,
  options,
  onChange,
  invalid,
}: {
  name: string
  value: T | ''
  options: Option<T>[]
  onChange: (value: T) => void
  invalid?: boolean
}) {
  return (
    <div role="radiogroup" aria-invalid={invalid} className="space-y-2">
      {options.map((option) => (
        <label key={option.value} className="flex items-start gap-2 text-sm text-foreground-body">
          <input
            type="radio"
            name={name}
            value={option.value}
            checked={value === option.value}
            onChange={() => onChange(option.value)}
            className="mt-0.5 size-4 accent-[var(--accent)]"
          />
          <span>
            {option.label}
            {option.hint && (
              <span className="mt-0.5 block text-xs text-foreground-muted">{option.hint}</span>
            )}
          </span>
        </label>
      ))}
    </div>
  )
}

function YesNo({
  name,
  value,
  onChange,
  yes = 'Sí',
  no = 'No',
}: {
  name: string
  value: boolean | null
  onChange: (value: boolean) => void
  yes?: string
  no?: string
}) {
  return (
    <RadioGroup
      name={name}
      value={value === null ? '' : value ? 'yes' : 'no'}
      options={[
        { value: 'yes', label: yes },
        { value: 'no', label: no },
      ]}
      onChange={(next) => onChange(next === 'yes')}
    />
  )
}

function FieldError({ errors, path }: { errors: FieldErrors; path: string }) {
  const messages = errors[path]
  if (!messages?.length) return null
  return (
    <p role="alert" className="mt-1.5 text-xs text-danger-foreground">
      {messages.join(' ')}
    </p>
  )
}

function Section({
  title,
  description,
  children,
}: {
  title: string
  description?: string
  children: ReactNode
}) {
  return (
    <section className="border-t border-border-subtle pt-5 first:border-t-0 first:pt-0">
      <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      {description && <p className="mt-1 text-xs text-foreground-muted">{description}</p>}
      <div className="mt-3 space-y-4">{children}</div>
    </section>
  )
}

const FAULT_OPTIONS: Option<'store' | 'customer'>[] = [
  { value: 'store', label: 'La tienda' },
  { value: 'customer', label: 'El cliente' },
]

const KIND_OPTIONS: Option<ExchangeKind>[] = [
  { value: 'variant', label: 'Otra talla o color del mismo producto' },
  { value: 'product', label: 'Otro producto' },
]

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('es-ES', { dateStyle: 'medium', timeStyle: 'short' })
}

export function ReturnsPolicyForm({ tenantId }: { tenantId: string }) {
  const { data, isLoading, isError, refetch } = useReturnsPolicy(tenantId)
  const saveMutation = useSaveReturnsPolicy(tenantId)
  const [form, setForm] = useState<PolicyForm | null>(null)
  const [loadedVersion, setLoadedVersion] = useState<number | null>(null)
  const [errors, setErrors] = useState<FieldErrors>({})
  const [stale, setStale] = useState<string | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [savedVersion, setSavedVersion] = useState<number | null>(null)

  // Solo la primera carga rellena el formulario: un refetch no pisa lo que se está editando.
  useEffect(() => {
    if (!data || form) return
    setForm(fromPolicy(data.policy))
    setLoadedVersion(data.version)
  }, [data, form])

  function edit(change: (current: PolicyForm) => PolicyForm) {
    setForm((current) => (current ? change(current) : current))
    setSavedVersion(null)
  }

  function patch(partial: Partial<PolicyForm>) {
    edit((current) => ({ ...current, ...partial }))
  }

  function patchReason(index: number, partial: Partial<ReasonRow>) {
    edit((current) => ({
      ...current,
      reasons: current.reasons.map((row, i) => (i === index ? { ...row, ...partial } : row)),
    }))
  }

  function changeLabel(index: number, label: string) {
    edit((current) => ({
      ...current,
      reasons: current.reasons.map((row, i) =>
        i === index
          ? { ...row, label, code: row.codeEdited ? row.code : slugifyCode(label) }
          : row,
      ),
    }))
  }

  async function reload() {
    const fresh = await refetch()
    if (!fresh.data) return
    setForm(fromPolicy(fresh.data.policy))
    setLoadedVersion(fresh.data.version)
    setStale(null)
    setErrors({})
    setFailure(null)
  }

  async function save() {
    if (!form) return
    setStale(null)
    setFailure(null)
    setSavedVersion(null)
    const result = toPayload(form)
    if (!result.ok) {
      setErrors(result.errors)
      return
    }
    setErrors({})
    try {
      const saved = await saveMutation.mutateAsync({
        policy: result.policy,
        expectedVersion: loadedVersion,
      })
      setForm(fromPolicy(saved.policy))
      setLoadedVersion(saved.version)
      setSavedVersion(saved.version)
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setStale(error.message)
      } else if (error instanceof ApiError && error.status === 422) {
        const body = error.body as { detail?: unknown }
        setErrors(fieldErrorsFrom422(body.detail))
      } else {
        setFailure(error instanceof Error ? error.message : 'No se pudo guardar')
      }
    }
  }

  if (isLoading || (data && !form)) return <Skeleton className="h-[720px]" />

  if (isError || !data || !form) {
    return (
      <div className="rounded-md border border-danger bg-danger-subtle px-4 py-3 text-sm text-danger-foreground">
        No se pudo cargar la política de devoluciones.
      </div>
    )
  }

  const customerShips = form.method === 'customer_ships'
  const customerPays = form.payerStoreFault === 'customer' || form.payerCustomerFault === 'customer'
  const showFee = form.method === 'store_label' && customerPays
  const summary = allMessages(errors)
  const err = (path: string) => Boolean(errors[path]?.length)

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
      <Card className="space-y-5 p-(--density-card-p)">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-foreground">Política de devoluciones</h2>
            <p className="mt-1 max-w-2xl text-sm text-foreground-muted">
              El agente aplica estas reglas tal cual. Cada guardado crea una versión nueva con tu
              nombre.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {savedVersion !== null && (
              <span className="text-xs text-success-foreground">
                Guardado (versión {savedVersion})
              </span>
            )}
            <Button onClick={save} disabled={saveMutation.isPending}>
              <Save className="size-4" />
              {saveMutation.isPending ? 'Guardando' : 'Guardar'}
            </Button>
          </div>
        </div>

        {data.policy === null && (
          <div className="flex gap-2 rounded-md bg-warning-subtle px-4 py-3 text-sm text-warning-foreground">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" />
            <p>
              {data.version === null
                ? 'Sin política configurada: el agente no abre devoluciones ni cambios y pasa cada caso a tu equipo.'
                : `La política guardada (versión ${data.version}) no se puede leer. Mientras tanto, el agente no abre devoluciones ni cambios y pasa cada caso a tu equipo. Guarda una versión nueva para sustituirla.`}
            </p>
          </div>
        )}

        {stale && (
          <div className="rounded-md bg-danger-subtle px-4 py-3 text-sm text-danger-foreground">
            <p>{stale}</p>
            <Button variant="outline" size="sm" className="mt-2" onClick={reload}>
              Recargar la política
            </Button>
          </div>
        )}

        {failure && (
          <div className="rounded-md bg-danger-subtle px-4 py-3 text-sm text-danger-foreground">
            {failure}
          </div>
        )}

        {summary.length > 0 && (
          <div role="alert" className="rounded-md bg-danger-subtle px-4 py-3 text-sm text-danger-foreground">
            <p className="font-medium">
              {summary.length === 1 ? 'Hay 1 punto que corregir:' : `Hay ${summary.length} puntos que corregir:`}
            </p>
            <ul className="mt-1 list-disc pl-5">
              {summary.map((message, index) => (
                <li key={`${index}-${message}`}>{message}</li>
              ))}
            </ul>
          </div>
        )}

        <Section title="Plazo">
          <div>
            <Label htmlFor="rp-days">Días para devolver</Label>
            <Input
              id="rp-days"
              inputMode="numeric"
              className="mt-1.5 w-32"
              value={form.windowDays}
              aria-invalid={err('window.days')}
              onChange={(event) => patch({ windowDays: event.target.value })}
            />
            <FieldError errors={errors} path="window.days" />
          </div>
          <div>
            <Label>El plazo cuenta desde</Label>
            <div className="mt-2">
              <RadioGroup
                name="rp-starts-at"
                value={form.startsAt}
                invalid={err('window.starts_at')}
                onChange={(startsAt) => patch({ startsAt })}
                options={[
                  {
                    value: 'delivery',
                    label: 'La entrega',
                    hint: 'Necesita que el transportista marque la entrega en Shopify. Si un pedido no tiene fecha de entrega, el agente pasa el caso a tu equipo.',
                  },
                  { value: 'shipment', label: 'El envío' },
                  { value: 'order', label: 'El pedido' },
                ]}
              />
            </div>
            <FieldError errors={errors} path="window.starts_at" />
          </div>
        </Section>

        <Section
          title="Motivos"
          description="Lista cerrada: el agente solo ofrece estos motivos al cliente."
        >
          {form.reasons.length === 0 && (
            <p className="text-sm text-foreground-muted">Aún no hay motivos.</p>
          )}
          {form.reasons.map((reason, index) => {
            const at = (field: string) => `reasons.${index}.${field}`
            return (
              <div
                key={index}
                className="space-y-3 rounded-md border border-border-subtle bg-surface-muted p-3"
              >
                <div className="grid gap-3 md:grid-cols-2">
                  <div>
                    <Label htmlFor={`rp-label-${index}`}>Nombre</Label>
                    <Input
                      id={`rp-label-${index}`}
                      className="mt-1.5"
                      value={reason.label}
                      placeholder="Llegó defectuoso"
                      aria-invalid={err(at('label'))}
                      onChange={(event) => changeLabel(index, event.target.value)}
                    />
                    <FieldError errors={errors} path={at('label')} />
                  </div>
                  <div>
                    <Label htmlFor={`rp-code-${index}`}>Código</Label>
                    <Input
                      id={`rp-code-${index}`}
                      className="mt-1.5 font-mono text-xs"
                      value={reason.code}
                      aria-invalid={err(at('code'))}
                      onChange={(event) =>
                        patchReason(index, { code: event.target.value, codeEdited: true })
                      }
                    />
                    <p className="mt-1.5 text-xs text-foreground-muted">
                      Cambiarlo afecta a las devoluciones futuras.
                    </p>
                    <FieldError errors={errors} path={at('code')} />
                  </div>
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  <div>
                    <Label>Culpa</Label>
                    <div className="mt-2 flex gap-4">
                      <RadioGroup
                        name={`rp-fault-${index}`}
                        value={reason.fault}
                        invalid={err(at('fault'))}
                        options={FAULT_OPTIONS}
                        onChange={(fault) => patchReason(index, { fault })}
                      />
                    </div>
                    <FieldError errors={errors} path={at('fault')} />
                  </div>
                  <div>
                    <Label htmlFor={`rp-shopify-${index}`}>Motivo de Shopify</Label>
                    <select
                      id={`rp-shopify-${index}`}
                      className={`${SELECT_CLASS} mt-1.5`}
                      value={reason.shopifyReason}
                      aria-invalid={err(at('shopify_reason'))}
                      onChange={(event) => patchReason(index, { shopifyReason: event.target.value })}
                    >
                      <option value="">Ninguno</option>
                      {SHOPIFY_REASONS.map((handle) => (
                        <option key={handle} value={handle}>
                          {SHOPIFY_REASON_LABELS[handle]}
                        </option>
                      ))}
                    </select>
                    <FieldError errors={errors} path={at('shopify_reason')} />
                  </div>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <label className="flex items-center gap-2 text-sm text-foreground-body">
                    <input
                      type="checkbox"
                      checked={reason.photo}
                      onChange={(event) => patchReason(index, { photo: event.target.checked })}
                      className="size-4 rounded border-border accent-[var(--accent)]"
                    />
                    Exige foto
                  </label>
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label={`Quitar el motivo ${reason.label || index + 1}`}
                    onClick={() =>
                      edit((current) => ({
                        ...current,
                        reasons: current.reasons.filter((_, i) => i !== index),
                      }))
                    }
                  >
                    <Trash2 className="size-4" />
                    Quitar
                  </Button>
                </div>
              </div>
            )
          })}
          <FieldError errors={errors} path="reasons" />
          <Button
            variant="outline"
            size="sm"
            disabled={form.reasons.length >= MAX_REASONS}
            onClick={() => edit((current) => ({ ...current, reasons: [...current.reasons, emptyReason()] }))}
          >
            <Plus className="size-4" />
            Añadir motivo
          </Button>
        </Section>

        <Section title="Envío de vuelta">
          <div>
            <Label>Cómo vuelve el paquete</Label>
            <div className="mt-2">
              <RadioGroup
                name="rp-method"
                value={form.method}
                invalid={err('shipping.method')}
                onChange={(method) => patch({ method })}
                options={[
                  { value: 'customer_ships', label: 'El cliente lo envía por su cuenta' },
                  { value: 'store_label', label: 'La tienda envía una etiqueta de devolución' },
                ]}
              />
            </div>
            <FieldError errors={errors} path="shipping.method" />
          </div>
          {customerShips && (
            <div>
              <Label htmlFor="rp-address">Dirección de devolución</Label>
              <Input
                id="rp-address"
                className="mt-1.5"
                value={form.returnAddress}
                placeholder="Calle Mayor 1, 28013 Madrid"
                aria-invalid={err('shipping.return_address')}
                onChange={(event) => patch({ returnAddress: event.target.value })}
              />
              <FieldError errors={errors} path="shipping.return_address" />
            </div>
          )}
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <Label>Si la culpa es de la tienda, paga el envío</Label>
              <div className="mt-2">
                <RadioGroup
                  name="rp-payer-store"
                  value={form.payerStoreFault}
                  invalid={err('shipping.payer.store_fault')}
                  options={FAULT_OPTIONS}
                  onChange={(payerStoreFault) => patch({ payerStoreFault })}
                />
              </div>
              <FieldError errors={errors} path="shipping.payer.store_fault" />
            </div>
            <div>
              <Label>Si la culpa es del cliente, paga el envío</Label>
              <div className="mt-2">
                <RadioGroup
                  name="rp-payer-customer"
                  value={form.payerCustomerFault}
                  invalid={err('shipping.payer.customer_fault')}
                  options={FAULT_OPTIONS}
                  onChange={(payerCustomerFault) => patch({ payerCustomerFault })}
                />
              </div>
              <FieldError errors={errors} path="shipping.payer.customer_fault" />
            </div>
          </div>
          {showFee && (
            <div>
              <Label htmlFor="rp-fee">Tarifa que se descuenta del reembolso</Label>
              <div className="mt-1.5 flex items-center gap-2">
                <Input
                  id="rp-fee"
                  inputMode="decimal"
                  className="w-32"
                  value={form.feeAmount}
                  placeholder="4.95"
                  aria-invalid={err('shipping.customer_fee.amount') || err('shipping.customer_fee')}
                  onChange={(event) => patch({ feeAmount: event.target.value })}
                />
                <Input
                  aria-label="Moneda"
                  className="w-24 uppercase"
                  maxLength={3}
                  value={form.feeCurrency}
                  placeholder="EUR"
                  aria-invalid={err('shipping.customer_fee.currency')}
                  onChange={(event) => patch({ feeCurrency: event.target.value })}
                />
              </div>
              <FieldError errors={errors} path="shipping.customer_fee.amount" />
              <FieldError errors={errors} path="shipping.customer_fee.currency" />
            </div>
          )}
          <FieldError errors={errors} path="shipping.customer_fee" />
          <FieldError errors={errors} path="shipping" />
        </Section>

        <Section title="Reembolso">
          <div>
            <Label htmlFor="rp-refund">Días para reembolsar desde que recibes el artículo</Label>
            <Input
              id="rp-refund"
              inputMode="numeric"
              className="mt-1.5 w-32"
              value={form.refundDays}
              aria-invalid={err('refund_days')}
              onChange={(event) => patch({ refundDays: event.target.value })}
            />
            <FieldError errors={errors} path="refund_days" />
          </div>
        </Section>

        <Section
          title="Exclusiones"
          description="Los productos con alguna de estas etiquetas de Shopify no admiten devolución."
        >
          <div>
            <Label htmlFor="rp-tags">Etiquetas de producto, separadas por coma</Label>
            <Input
              id="rp-tags"
              className="mt-1.5"
              value={form.excludedTags}
              placeholder="liquidacion, tarjeta-regalo"
              onChange={(event) => patch({ excludedTags: event.target.value })}
            />
            <FieldError errors={errors} path="excluded_product_tags" />
          </div>
        </Section>

        <Section title="Cambios">
          <div>
            <Label>¿Admites cambios?</Label>
            <div className="mt-2">
              <YesNo
                name="rp-exchanges"
                value={form.exchangesEnabled}
                onChange={(exchangesEnabled) => patch({ exchangesEnabled })}
              />
            </div>
            <FieldError errors={errors} path="exchanges.enabled" />
          </div>
          {form.exchangesEnabled && (
            <div>
              <Label>Tipos de cambio</Label>
              <div className="mt-2 space-y-2">
                {KIND_OPTIONS.map((option) => (
                  <label key={option.value} className="flex items-center gap-2 text-sm text-foreground-body">
                    <input
                      type="checkbox"
                      checked={form.exchangeKinds.includes(option.value)}
                      onChange={(event) =>
                        patch({
                          exchangeKinds: event.target.checked
                            ? [...form.exchangeKinds, option.value]
                            : form.exchangeKinds.filter((kind) => kind !== option.value),
                        })
                      }
                      className="size-4 rounded border-border accent-[var(--accent)]"
                    />
                    {option.label}
                  </label>
                ))}
              </div>
              <FieldError errors={errors} path="exchanges.kinds" />
            </div>
          )}
          <FieldError errors={errors} path="exchanges" />
          <p className="text-xs text-foreground-muted">Los cambios siempre pasan por tu aprobación.</p>
        </Section>

        <Section title="Aprobación">
          <div>
            <Label>Las devoluciones sin cambio necesitan mi aprobación</Label>
            <div className="mt-2">
              <YesNo
                name="rp-approval"
                value={form.requireApproval}
                onChange={(requireApproval) => patch({ requireApproval })}
              />
            </div>
            <FieldError errors={errors} path="returns_require_approval" />
          </div>
        </Section>
      </Card>

      <Card className="h-fit p-(--density-card-p)">
        <div className="flex items-center justify-between">
          <p className="text-sm font-semibold text-foreground">Historial</p>
          <History className="size-4 text-foreground-muted" />
        </div>
        {data.history.length === 0 ? (
          <p className="mt-3 text-sm text-foreground-muted">Todavía no hay versiones guardadas.</p>
        ) : (
          <ul className="mt-3 divide-y divide-border-subtle">
            {data.history.map((entry) => (
              <li key={entry.version} className="py-2 text-sm">
                <p className="font-medium text-foreground">Versión {entry.version}</p>
                <p className="text-xs text-foreground-muted">
                  {entry.edited_by_email ?? 'Sin autor'} · {formatDate(entry.created_at)}
                </p>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
