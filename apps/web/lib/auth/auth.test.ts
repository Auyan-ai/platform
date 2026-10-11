import { describe, expect, it, vi } from 'vitest'
import { decideMagicAccess, landingPathFor } from './access'
import { type CallbackDeps, resolveCallback } from './callback'
import {
  linkErrorCode,
  loginErrorMessage,
  passwordErrorMessage,
  signInErrorMessage,
} from './messages'
import { validateNewPassword } from './password'

const TENANT = '11111111-1111-1111-1111-111111111111'
const tenantAdmin = { user_id: 'u', tenant_id: TENANT, role: 'tenant_admin', email: 'a@b.c' }
const superAdmin = { user_id: 's', tenant_id: null, role: 'super_admin', email: 's@b.c' }

function deps(over: Partial<CallbackDeps> = {}): CallbackDeps {
  return {
    exchangeCode: vi.fn(async () => ({ accessToken: 'tok', userMetadata: {}, error: null })),
    signOut: vi.fn(async () => {}),
    fetchUser: vi.fn(async () => tenantAdmin),
    ...over,
  }
}

const q = (s: string) => new URLSearchParams(s)

describe('decideMagicAccess', () => {
  it('permite tenant_admin y aterriza en su overview', () => {
    expect(decideMagicAccess(tenantAdmin)).toEqual({
      ok: true,
      landing: `/clients/${TENANT}/overview`,
    })
  })
  it('rechaza super_admin con password_required', () => {
    expect(decideMagicAccess(superAdmin)).toEqual({ ok: false, error: 'password_required' })
  })
  it('falla cerrado si no se resuelve el rol', () => {
    expect(decideMagicAccess(null)).toEqual({ ok: false, error: 'verify_failed' })
  })
  it('landingPathFor manda al resto a la raíz', () => {
    expect(landingPathFor(superAdmin)).toBe('/')
    expect(landingPathFor(null)).toBe('/')
  })
})

describe('resolveCallback', () => {
  it('super_admin por enlace de acceso: cierra sesión y vuelve al login con el error', async () => {
    const d = deps({ fetchUser: vi.fn(async () => superAdmin) })
    const r = await resolveCallback(q('code=abc'), d)
    expect(d.signOut).toHaveBeenCalledOnce()
    expect(r).toEqual({ redirectTo: '/login?error=password_required', requirePassword: false })
    expect(loginErrorMessage('password_required')).toBe('Debes entrar con tu usuario y contraseña.')
  })

  it('si /users/me falla, cierra sesión y no deja entrar', async () => {
    const d = deps({ fetchUser: vi.fn(async () => null) })
    const r = await resolveCallback(q('code=abc'), d)
    expect(d.signOut).toHaveBeenCalledOnce()
    expect(r.redirectTo).toBe('/login?error=verify_failed')
  })

  it('tenant_admin sin contraseña fijada ve la pantalla saltable', async () => {
    const r = await resolveCallback(q('code=abc'), deps())
    expect(r).toEqual({ redirectTo: '/auth/set-password?mode=magic', requirePassword: false })
  })

  it.each([{ password_set: true }, { password_prompt_dismissed: true }])(
    'tenant_admin con decisión previa (%o) va directo a su overview',
    async (meta) => {
      const d = deps({
        exchangeCode: vi.fn(async () => ({ accessToken: 'tok', userMetadata: meta, error: null })),
      })
      const r = await resolveCallback(q('code=abc'), d)
      expect(r.redirectTo).toBe(`/clients/${TENANT}/overview`)
      expect(d.signOut).not.toHaveBeenCalled()
    },
  )

  it('recuperación vale para super_admin y obliga a fijar contraseña', async () => {
    const d = deps({ fetchUser: vi.fn(async () => superAdmin) })
    const r = await resolveCallback(q('code=abc&flow=recovery'), d)
    expect(r).toEqual({ redirectTo: '/auth/set-password?mode=recovery', requirePassword: true })
    expect(d.signOut).not.toHaveBeenCalled()
  })

  it('sin code o con error de Supabase vuelve al login con error explícito', async () => {
    expect((await resolveCallback(q(''), deps())).redirectTo).toBe('/login?error=link_invalid')
    expect(
      (await resolveCallback(q('error=access_denied&error_code=otp_expired'), deps())).redirectTo,
    ).toBe('/login?error=link_expired')
  })

  it('error al canjear el code: caducado / ya usado / inválido', async () => {
    const withErr = (error: { code?: string; message?: string }) =>
      deps({
        exchangeCode: vi.fn(async () => ({ accessToken: null, userMetadata: {}, error })),
      })
    expect(
      (await resolveCallback(q('code=x'), withErr({ code: 'flow_state_expired' }))).redirectTo,
    ).toBe('/login?error=link_expired')
    expect(
      (await resolveCallback(q('code=x'), withErr({ code: 'flow_state_not_found' }))).redirectTo,
    ).toBe('/login?error=link_used')
    expect((await resolveCallback(q('code=x'), withErr({ message: 'boom' }))).redirectTo).toBe(
      '/login?error=link_invalid',
    )
  })
})

describe('mensajes y validación', () => {
  it('traduce errores de Supabase', () => {
    expect(linkErrorCode({ code: 'otp_expired' })).toBe('link_expired')
    expect(passwordErrorMessage({ code: 'weak_password' })).toMatch(/demasiado débil/)
    expect(passwordErrorMessage({ code: 'same_password' })).toMatch(/distinta/)
    expect(signInErrorMessage({ code: 'invalid_credentials' })).toBe(
      'Email o contraseña incorrectos.',
    )
    expect(signInErrorMessage({ status: 429 })).toMatch(/Demasiados intentos/)
  })
  it('código de error desconocido en la URL no filtra texto arbitrario', () => {
    expect(loginErrorMessage('<script>')).toBe(loginErrorMessage('link_invalid'))
    expect(loginErrorMessage(null)).toBeNull()
  })
  it('valida contraseña nueva', () => {
    expect(validateNewPassword('corta', 'corta')).toMatch(/al menos 8/)
    expect(validateNewPassword('suficiente1', 'otra-cosa1')).toBe('Las contraseñas no coinciden.')
    expect(validateNewPassword('suficiente1', 'suficiente1')).toBeNull()
  })
})
