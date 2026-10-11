import type { CurrentUser } from '@/lib/api/users'
import { decideMagicAccess } from './access'
import { SET_PASSWORD_PATH } from './constants'
import { type AuthErrorLike, type LoginErrorCode, linkErrorCode } from './messages'

export interface CallbackDeps {
  exchangeCode(code: string): Promise<{
    accessToken: string | null
    userMetadata: Record<string, unknown>
    error: AuthErrorLike | null
  }>
  signOut(): Promise<void>
  fetchUser(token: string): Promise<CurrentUser | null>
}

export interface CallbackResult {
  redirectTo: string
  /** Activa la cookie que obliga a fijar contraseña antes de entrar al dashboard. */
  requirePassword: boolean
}

function toLogin(error: LoginErrorCode): CallbackResult {
  return { redirectTo: `/login?error=${error}`, requirePassword: false }
}

/**
 * Lógica del callback de Supabase Auth (servidor), separada de la ruta para poder probarla.
 * - `flow=recovery`: vale para cualquier rol; obliga a fijar contraseña nueva.
 * - resto (enlace de acceso): solo `tenant_admin`; cualquier otro rol se desloguea y vuelve al login.
 *   La comprobación va aquí (tras el clic) y no al pedir el enlace, para no enumerar super_admins.
 */
export async function resolveCallback(
  params: URLSearchParams,
  deps: CallbackDeps,
): Promise<CallbackResult> {
  const isRecovery = params.get('flow') === 'recovery'

  const errorCode = params.get('error_code') ?? params.get('error')
  if (errorCode) {
    return toLogin(
      linkErrorCode({ code: errorCode, message: params.get('error_description') ?? '' }),
    )
  }

  const code = params.get('code')
  if (!code) return toLogin('link_invalid')

  const exchanged = await deps.exchangeCode(code)
  if (exchanged.error || !exchanged.accessToken) {
    return toLogin(linkErrorCode(exchanged.error))
  }

  if (isRecovery) {
    return { redirectTo: `${SET_PASSWORD_PATH}?mode=recovery`, requirePassword: true }
  }

  const access = decideMagicAccess(await deps.fetchUser(exchanged.accessToken))
  if (!access.ok) {
    await deps.signOut()
    return toLogin(access.error)
  }

  const meta = exchanged.userMetadata
  const alreadyDecided = meta.password_set === true || meta.password_prompt_dismissed === true
  if (!alreadyDecided) {
    return { redirectTo: `${SET_PASSWORD_PATH}?mode=magic`, requirePassword: false }
  }
  return { redirectTo: access.landing, requirePassword: false }
}
