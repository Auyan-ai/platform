import { describe, expect, it } from 'vitest'
import {
  type PolicyForm,
  type ReturnsPolicy,
  emptyForm,
  fieldErrorsFrom422,
  fromPolicy,
  parseTags,
  slugifyCode,
  toPayload,
} from './returns-policy'

const POLICY: ReturnsPolicy = {
  schema_version: 1,
  window: { days: 14, starts_at: 'delivery' },
  reasons: [
    {
      code: 'defectuoso',
      label: 'Llegó defectuoso',
      fault: 'store',
      required_evidence: ['photo'],
      shopify_reason: 'damaged-or-defective',
    },
    {
      code: 'no_me_gusta',
      label: 'No me gusta',
      fault: 'customer',
      required_evidence: [],
      shopify_reason: null,
    },
  ],
  shipping: {
    method: 'store_label',
    return_address: null,
    payer: { store_fault: 'store', customer_fault: 'customer' },
    customer_fee: { amount: '4.95', currency: 'EUR' },
  },
  refund_days: 10,
  excluded_product_tags: ['final-sale', 'gift-card'],
  exchanges: { enabled: true, kinds: ['variant'] },
  returns_require_approval: false,
}

function validForm(): PolicyForm {
  return fromPolicy(POLICY)
}

describe('fromPolicy / toPayload', () => {
  it('ida y vuelta de una política completa', () => {
    expect(toPayload(fromPolicy(POLICY))).toEqual({ ok: true, policy: POLICY })
  })

  it('sin política el formulario arranca vacío y sin valores de negocio', () => {
    const form = fromPolicy(null)
    expect(form).toEqual(emptyForm())
    expect(form.windowDays).toBe('')
    expect(form.startsAt).toBe('')
    expect(form.exchangesEnabled).toBeNull()
    expect(form.requireApproval).toBeNull()
  })

  it('el formulario vacío no valida y marca cada sección', () => {
    const result = toPayload(emptyForm())
    expect(result.ok).toBe(false)
    if (result.ok) return
    expect(Object.keys(result.errors).sort()).toEqual([
      'exchanges.enabled',
      'reasons',
      'refund_days',
      'returns_require_approval',
      'shipping.method',
      'shipping.payer.customer_fault',
      'shipping.payer.store_fault',
      'window.days',
      'window.starts_at',
    ])
    expect(result.errors['window.days']).toEqual(['Indica los días'])
  })

  it('customer_ships quita la tarifa aunque quede escrita y conserva la dirección', () => {
    const form: PolicyForm = {
      ...validForm(),
      method: 'customer_ships',
      returnAddress: '  Calle Mayor 1, Madrid ',
      feeAmount: '4.95',
      feeCurrency: 'EUR',
    }
    const result = toPayload(form)
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.policy.shipping).toEqual({
      method: 'customer_ships',
      return_address: 'Calle Mayor 1, Madrid',
      payer: { store_fault: 'store', customer_fault: 'customer' },
      customer_fee: null,
    })
  })

  it('store_label quita la dirección y la tarifa si paga siempre la tienda', () => {
    const form: PolicyForm = {
      ...validForm(),
      returnAddress: 'Calle Mayor 1, Madrid',
      payerCustomerFault: 'store',
    }
    const result = toPayload(form)
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.policy.shipping.return_address).toBeNull()
    expect(result.policy.shipping.customer_fee).toBeNull()
  })

  it('customer_ships sin dirección falla en shipping.return_address', () => {
    const result = toPayload({ ...validForm(), method: 'customer_ships', returnAddress: '' })
    expect(result).toEqual({
      ok: false,
      errors: { 'shipping.return_address': ['Si el cliente envía, indica la dirección de devolución'] },
    })
  })

  it('store_label con el cliente pagando exige tarifa', () => {
    const result = toPayload({ ...validForm(), feeAmount: '' })
    expect(result.ok).toBe(false)
    if (result.ok) return
    expect(result.errors['shipping.customer_fee.amount']).toEqual([
      'Importe no válido (máximo 2 decimales)',
    ])
  })

  it('acepta coma decimal y minúsculas en la moneda', () => {
    const result = toPayload({ ...validForm(), feeAmount: '3,5', feeCurrency: 'eur' })
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.policy.shipping.customer_fee).toEqual({ amount: '3.5', currency: 'EUR' })
  })

  it('rechaza más de 2 decimales', () => {
    const result = toPayload({ ...validForm(), feeAmount: '3.555' })
    expect(result.ok).toBe(false)
  })

  it('cambios activados sin tipos falla en exchanges.kinds', () => {
    const result = toPayload({ ...validForm(), exchangeKinds: [] })
    expect(result).toEqual({
      ok: false,
      errors: { 'exchanges.kinds': ['Elige al menos un tipo de cambio'] },
    })
  })

  it('cambios desactivados descartan los tipos marcados', () => {
    const result = toPayload({ ...validForm(), exchangesEnabled: false })
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.policy.exchanges).toEqual({ enabled: false, kinds: [] })
  })

  it('códigos de motivo repetidos fallan en el segundo', () => {
    const form = validForm()
    form.reasons[1] = { ...form.reasons[1], code: 'defectuoso' }
    expect(toPayload(form)).toEqual({
      ok: false,
      errors: { 'reasons.1.code': ['Este código ya lo usa otro motivo'] },
    })
  })

  it('valida plazo y reembolso en rango', () => {
    const result = toPayload({ ...validForm(), windowDays: '400', refundDays: '0' })
    expect(result.ok).toBe(false)
    if (result.ok) return
    expect(result.errors['window.days']).toEqual(['Entre 1 y 365 días'])
    expect(result.errors.refund_days).toEqual(['Entre 1 y 60 días'])
  })

  it('un plazo no numérico cuenta como vacío', () => {
    const result = toPayload({ ...validForm(), windowDays: '14 días' })
    expect(result.ok).toBe(false)
    if (result.ok) return
    expect(result.errors['window.days']).toEqual(['Indica los días'])
  })

  it('motivo sin culpa ni nombre marca ambos campos', () => {
    const form = validForm()
    form.reasons[0] = { ...form.reasons[0], label: '  ', fault: '' }
    const result = toPayload(form)
    expect(result.ok).toBe(false)
    if (result.ok) return
    expect(result.errors['reasons.0.label']).toEqual(['Escribe el nombre del motivo'])
    expect(result.errors['reasons.0.fault']).toEqual(['Indica de quién es la culpa'])
  })

  it('más de 20 motivos falla', () => {
    const form = validForm()
    form.reasons = Array.from({ length: 21 }, (_, i) => ({
      ...form.reasons[0],
      label: `Motivo ${i}`,
      code: `motivo_${i}`,
    }))
    const result = toPayload(form)
    expect(result.ok).toBe(false)
    if (result.ok) return
    expect(result.errors.reasons).toEqual(['Máximo 20 motivos'])
  })
})

describe('slugifyCode', () => {
  it('quita tildes y signos', () => {
    expect(slugifyCode('Llegó defectuoso')).toBe('llego_defectuoso')
    expect(slugifyCode('¿Talla pequeña?')).toBe('talla_pequena')
  })

  it('antepone m_ si empieza por número y corta a 40', () => {
    expect(slugifyCode('30 días')).toBe('m_30_dias')
    expect(slugifyCode('a'.repeat(60))).toHaveLength(40)
  })

  it('devuelve vacío si no queda nada', () => {
    expect(slugifyCode('¡¡¡')).toBe('')
  })
})

describe('parseTags', () => {
  it('separa por coma, recorta y quita duplicados', () => {
    expect(parseTags(' final-sale, gift-card ,,final-sale')).toEqual(['final-sale', 'gift-card'])
  })
})

describe('fieldErrorsFrom422', () => {
  it('asigna cada mensaje a su ruta y quita el prefijo de Pydantic', () => {
    const detail = [
      {
        loc: ['body', 'policy', 'shipping'],
        msg: 'Value error, customer_ships exige return_address',
        type: 'value_error',
      },
      { loc: ['body', 'policy', 'reasons', 0, 'code'], msg: 'String should match pattern' },
    ]
    expect(fieldErrorsFrom422(detail)).toEqual({
      shipping: ['customer_ships exige return_address'],
      'reasons.0.code': ['String should match pattern'],
    })
  })

  it('lo que no cuelga de la política va a la clave general', () => {
    expect(
      fieldErrorsFrom422([{ loc: ['body', 'expected_version'], msg: 'Field required' }]),
    ).toEqual({ _: ['Field required'] })
  })

  it('un detail de texto va a la clave general y otro tipo se ignora', () => {
    expect(fieldErrorsFrom422('Algo falló')).toEqual({ _: ['Algo falló'] })
    expect(fieldErrorsFrom422(null)).toEqual({})
  })
})
