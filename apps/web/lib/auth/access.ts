import type { CurrentUser } from '@/lib/api/users'
import type { LoginErrorCode } from './messages'

type UserRoleInfo = Pick<CurrentUser, 'role' | 'tenant_id'>

/** Ruta de aterrizaje tras autenticarse. */
export function landingPathFor(user: UserRoleInfo | null): string {
  if (user?.role === 'tenant_admin' && user.tenant_id) {
    return `/clients/${user.tenant_id}/overview`
  }
  return '/'
}

export type MagicAccess = { ok: true; landing: string } | { ok: false; error: LoginErrorCode }

/**
 * Entrar por enlace mágico solo vale para `tenant_admin`. El rol sale de GET /users/me
 * (la misma fuente que usa el resto de la web). Si no se puede resolver, se rechaza (falla cerrado).
 */
export function decideMagicAccess(user: UserRoleInfo | null): MagicAccess {
  if (!user) return { ok: false, error: 'verify_failed' }
  if (user.role === 'tenant_admin' && user.tenant_id) {
    return { ok: true, landing: landingPathFor(user) }
  }
  return { ok: false, error: 'password_required' }
}
