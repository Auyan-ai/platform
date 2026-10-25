import { describe, expect, it } from 'vitest'
import { demoBadgeLabel, isDemo, suggestClientSlug } from './demo'

describe('suggestClientSlug', () => {
  it('quita acentos y símbolos', () => {
    expect(suggestClientSlug('Ñandú Café & Co.')).toBe('nandu-cafe-co')
  })
})

describe('demoBadgeLabel', () => {
  it('muestra la fecha de caducidad en español', () => {
    expect(demoBadgeLabel('2026-11-24T12:00:00Z')).toBe('Demo · caduca 24 nov 2026')
  })

  it('cae a "Demo" si no hay fecha', () => {
    expect(demoBadgeLabel(null)).toBe('Demo')
  })
})

describe('isDemo', () => {
  it('distingue demos de clientes', () => {
    expect(isDemo({ origin: 'demo' })).toBe(true)
    expect(isDemo({ origin: 'client' })).toBe(false)
  })
})
