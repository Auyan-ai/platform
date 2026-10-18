import { z } from 'zod'

export type WindowStart = 'delivery' | 'shipment' | 'order'
export type Fault = 'store' | 'customer'
export type Payer = 'store' | 'customer'
export type ShippingMethod = 'customer_ships' | 'store_label'
export type ExchangeKind = 'variant' | 'product'

export interface ReturnsPolicy {
  schema_version: 1
  window: { days: number; starts_at: WindowStart }
  reasons: {
    code: string
    label: string
    fault: Fault
    required_evidence: 'photo'[]
    shopify_reason: string | null
  }[]
  shipping: {
    method: ShippingMethod
    return_address: string | null
    payer: { store_fault: Payer; customer_fault: Payer }
    customer_fee: { amount: string; currency: string } | null
  }
  refund_days: number
  excluded_product_tags: string[]
  exchanges: { enabled: boolean; kinds: ExchangeKind[] }
  returns_require_approval: boolean
}

export interface ReasonRow {
  label: string
  code: string
  codeEdited: boolean
  fault: Fault | ''
  photo: boolean
  shopifyReason: string
}

export interface PolicyForm {
  windowDays: string
  startsAt: WindowStart | ''
  reasons: ReasonRow[]
  method: ShippingMethod | ''
  returnAddress: string
  payerStoreFault: Payer | ''
  payerCustomerFault: Payer | ''
  feeAmount: string
  feeCurrency: string
  refundDays: string
  excludedTags: string
  exchangesEnabled: boolean | null
  exchangeKinds: ExchangeKind[]
  requireApproval: boolean | null
}

export type FieldErrors = Record<string, string[]>

export const MAX_REASONS = 20

export const SHOPIFY_REASONS = [
  'damaged-or-defective',
  'received-the-wrong-item',
  'item-not-as-described',
  'too-small',
  'too-big',
  'style',
  'color',
  'changed-my-mind',
  'other-reason',
] as const

// Sin valores de negocio por defecto (ADR 0014): todo arranca sin marcar.
export function emptyForm(): PolicyForm {
  return {
    windowDays: '',
    startsAt: '',
    reasons: [],
    method: '',
    returnAddress: '',
    payerStoreFault: '',
    payerCustomerFault: '',
    feeAmount: '',
    feeCurrency: '',
    refundDays: '',
    excludedTags: '',
    exchangesEnabled: null,
    exchangeKinds: [],
    requireApproval: null,
  }
}

export function emptyReason(): ReasonRow {
  return { label: '', code: '', codeEdited: false, fault: '', photo: false, shopifyReason: '' }
}

export function slugifyCode(label: string): string {
  const slug = label
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
  if (!slug) return ''
  const startsWithLetter = /^[a-z]/.test(slug)
  return (startsWithLetter ? slug : `m_${slug}`).slice(0, 40).replace(/_+$/, '')
}

export function fromPolicy(policy: ReturnsPolicy | null): PolicyForm {
  if (!policy) return emptyForm()
  return {
    windowDays: String(policy.window.days),
    startsAt: policy.window.starts_at,
    reasons: policy.reasons.map((r) => ({
      label: r.label,
      code: r.code,
      codeEdited: true,
      fault: r.fault,
      photo: r.required_evidence.includes('photo'),
      shopifyReason: r.shopify_reason ?? '',
    })),
    method: policy.shipping.method,
    returnAddress: policy.shipping.return_address ?? '',
    payerStoreFault: policy.shipping.payer.store_fault,
    payerCustomerFault: policy.shipping.payer.customer_fault,
    feeAmount: policy.shipping.customer_fee?.amount ?? '',
    feeCurrency: policy.shipping.customer_fee?.currency ?? '',
    refundDays: String(policy.refund_days),
    excludedTags: policy.excluded_product_tags.join(', '),
    exchangesEnabled: policy.exchanges.enabled,
    exchangeKinds: policy.exchanges.kinds,
    requireApproval: policy.returns_require_approval,
  }
}

function wholeNumber(raw: string): number | undefined {
  const text = raw.trim()
  return /^\d+$/.test(text) ? Number(text) : undefined
}

export function parseTags(raw: string): string[] {
  const seen = new Set<string>()
  for (const part of raw.split(',')) {
    const tag = part.trim()
    if (tag) seen.add(tag)
  }
  return [...seen]
}

// Borrador con el mismo contorno que ReturnsPolicy pero con huecos (undefined) donde el
// formulario está sin rellenar; el esquema los convierte en errores junto al campo.
function toDraft(form: PolicyForm): unknown {
  const customerPays = form.payerStoreFault === 'customer' || form.payerCustomerFault === 'customer'
  const storeLabel = form.method === 'store_label'
  const address = form.returnAddress.trim()
  return {
    schema_version: 1,
    window: { days: wholeNumber(form.windowDays), starts_at: form.startsAt || undefined },
    reasons: form.reasons.map((r) => ({
      code: r.code.trim(),
      label: r.label.trim(),
      fault: r.fault || undefined,
      required_evidence: r.photo ? ['photo'] : [],
      shopify_reason: r.shopifyReason || null,
    })),
    shipping: {
      method: form.method || undefined,
      return_address: storeLabel ? null : address || null,
      payer: {
        store_fault: form.payerStoreFault || undefined,
        customer_fault: form.payerCustomerFault || undefined,
      },
      customer_fee:
        storeLabel && customerPays
          ? {
              amount: form.feeAmount.trim().replace(',', '.'),
              currency: form.feeCurrency.trim().toUpperCase(),
            }
          : null,
    },
    refund_days: wholeNumber(form.refundDays),
    excluded_product_tags: parseTags(form.excludedTags),
    exchanges: {
      enabled: form.exchangesEnabled ?? undefined,
      kinds: form.exchangesEnabled ? form.exchangeKinds : [],
    },
    returns_require_approval: form.requireApproval ?? undefined,
  }
}

const requiredInt = (min: number, max: number, missing: string, range: string) =>
  z
    .number({ required_error: missing, invalid_type_error: missing })
    .int(range)
    .min(min, range)
    .max(max, range)

const payerSchema = z.enum(['store', 'customer'], {
  errorMap: () => ({ message: 'Elige quién paga' }),
})

const reasonSchema = z.object({
  code: z
    .string()
    .regex(
      /^[a-z][a-z0-9_]{1,39}$/,
      'Usa de 2 a 40 caracteres: minúsculas, números y guion bajo, empezando por letra',
    ),
  label: z.string().min(1, 'Escribe el nombre del motivo').max(80, 'Máximo 80 caracteres'),
  fault: z.enum(['store', 'customer'], {
    errorMap: () => ({ message: 'Indica de quién es la culpa' }),
  }),
  required_evidence: z.array(z.literal('photo')),
  shopify_reason: z
    .string()
    .regex(/^[a-z0-9][a-z0-9-]{1,59}$/, 'Motivo de Shopify no válido')
    .nullable(),
})

export const policySchema = z
  .object({
    schema_version: z.literal(1),
    window: z.object({
      days: requiredInt(1, 365, 'Indica los días', 'Entre 1 y 365 días'),
      starts_at: z.enum(['delivery', 'shipment', 'order'], {
        errorMap: () => ({ message: 'Elige desde qué evento cuenta el plazo' }),
      }),
    }),
    reasons: z
      .array(reasonSchema)
      .min(1, 'Añade al menos un motivo')
      .max(MAX_REASONS, `Máximo ${MAX_REASONS} motivos`),
    shipping: z.object({
      method: z.enum(['customer_ships', 'store_label'], {
        errorMap: () => ({ message: 'Elige cómo vuelve el paquete' }),
      }),
      return_address: z
        .string()
        .min(5, 'Mínimo 5 caracteres')
        .max(300, 'Máximo 300 caracteres')
        .nullable(),
      payer: z.object({ store_fault: payerSchema, customer_fault: payerSchema }),
      customer_fee: z
        .object({
          amount: z
            .string()
            .regex(/^\d{1,8}(\.\d{1,2})?$/, 'Importe no válido (máximo 2 decimales)'),
          currency: z.string().regex(/^[A-Z]{3}$/, 'Moneda de 3 letras, por ejemplo EUR'),
        })
        .nullable(),
    }),
    refund_days: requiredInt(1, 60, 'Indica los días', 'Entre 1 y 60 días'),
    excluded_product_tags: z.array(z.string().min(1)),
    exchanges: z.object({
      enabled: z.boolean({
        required_error: 'Indica si admites cambios',
        invalid_type_error: 'Indica si admites cambios',
      }),
      kinds: z.array(z.enum(['variant', 'product'])),
    }),
    returns_require_approval: z.boolean({
      required_error: 'Indica si las devoluciones necesitan tu aprobación',
      invalid_type_error: 'Indica si las devoluciones necesitan tu aprobación',
    }),
  })
  .superRefine((policy, ctx) => {
    const seen = new Set<string>()
    policy.reasons.forEach((reason, index) => {
      if (seen.has(reason.code)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['reasons', index, 'code'],
          message: 'Este código ya lo usa otro motivo',
        })
      }
      seen.add(reason.code)
    })

    const { shipping, exchanges } = policy
    const customerPays =
      shipping.payer.store_fault === 'customer' || shipping.payer.customer_fault === 'customer'
    if (shipping.method === 'customer_ships') {
      if (!shipping.return_address) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['shipping', 'return_address'],
          message: 'Si el cliente envía, indica la dirección de devolución',
        })
      }
      if (shipping.customer_fee) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['shipping', 'customer_fee'],
          message: 'La tarifa solo vale cuando la tienda pone la etiqueta',
        })
      }
    } else if (customerPays && !shipping.customer_fee) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['shipping', 'customer_fee'],
        message: 'Si el cliente paga con etiqueta de la tienda, indica la tarifa',
      })
    } else if (!customerPays && shipping.customer_fee) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['shipping', 'customer_fee'],
        message: 'La tarifa sobra: la tienda paga siempre el envío de vuelta',
      })
    }
    if (exchanges.enabled && exchanges.kinds.length === 0) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['exchanges', 'kinds'],
        message: 'Elige al menos un tipo de cambio',
      })
    }
  })

export type PayloadResult =
  | { ok: true; policy: ReturnsPolicy }
  | { ok: false; errors: FieldErrors }

function addError(errors: FieldErrors, path: string, message: string) {
  errors[path] = [...(errors[path] ?? []), message]
}

export function toPayload(form: PolicyForm): PayloadResult {
  const parsed = policySchema.safeParse(toDraft(form))
  if (parsed.success) return { ok: true, policy: parsed.data as ReturnsPolicy }
  const errors: FieldErrors = {}
  for (const issue of parsed.error.issues) {
    addError(errors, issue.path.join('.'), issue.message)
  }
  return { ok: false, errors }
}

export function fieldErrorsFrom422(detail: unknown): FieldErrors {
  const errors: FieldErrors = {}
  if (typeof detail === 'string') return { _: [detail] }
  if (!Array.isArray(detail)) return errors
  for (const item of detail) {
    if (!item || typeof item !== 'object') continue
    const { loc, msg } = item as { loc?: unknown; msg?: unknown }
    if (typeof msg !== 'string') continue
    const message = msg.replace(/^Value error, /, '')
    const parts = Array.isArray(loc) ? loc.map(String) : []
    const inPolicy = parts[0] === 'body' && parts[1] === 'policy'
    addError(errors, inPolicy ? parts.slice(2).join('.') || '_' : '_', message)
  }
  return errors
}

export function allMessages(errors: FieldErrors): string[] {
  return Object.values(errors).flat()
}
