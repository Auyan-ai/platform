/** Códigos de error que viajan en `/login?error=<código>` y su texto para el usuario. */
export const LOGIN_ERRORS = {
  password_required: 'Debes entrar con tu usuario y contraseña.',
  link_expired: 'El enlace ha caducado. Solicita uno nuevo.',
  link_used: 'Este enlace ya se usó. Solicita uno nuevo.',
  link_invalid: 'El enlace no es válido. Solicita uno nuevo desde este mismo navegador.',
  verify_failed:
    'No hemos podido verificar tu cuenta. Inténtalo de nuevo o entra con tu contraseña.',
} as const

export type LoginErrorCode = keyof typeof LOGIN_ERRORS

export function loginErrorMessage(code: string | null | undefined): string | null {
  if (!code) return null
  return code in LOGIN_ERRORS ? LOGIN_ERRORS[code as LoginErrorCode] : LOGIN_ERRORS.link_invalid
}

/** Respuesta única al pedir enlace de acceso o recuperación: no revela si el email existe. */
export const LINK_SENT_MESSAGE = 'Si el email existe, te llegará un enlace.'

export const RATE_LIMIT_MESSAGE = 'Demasiados intentos. Espera unos minutos y vuelve a probar.'

export interface AuthErrorLike {
  code?: string
  message?: string
  status?: number
}

/** Solo los rate limits se muestran: cualquier otro fallo al pedir enlaces responde igual. */
export function isRateLimit(error: AuthErrorLike | null | undefined): boolean {
  return (
    error?.status === 429 ||
    error?.code === 'over_email_send_rate_limit' ||
    error?.code === 'over_request_rate_limit'
  )
}

/** Clasifica un error al canjear un enlace (code PKCE) en un código de /login. */
export function linkErrorCode(error: AuthErrorLike | null | undefined): LoginErrorCode {
  const code = error?.code ?? ''
  const message = (error?.message ?? '').toLowerCase()
  if (code === 'otp_expired' || code === 'flow_state_expired' || message.includes('expired')) {
    return 'link_expired'
  }
  if (code === 'flow_state_not_found' || message.includes('no valid flow state')) {
    return 'link_used'
  }
  return 'link_invalid'
}

/** Traduce errores de signInWithPassword. */
export function signInErrorMessage(error: AuthErrorLike): string {
  if (
    error.code === 'invalid_credentials' ||
    /invalid login credentials/i.test(error.message ?? '')
  ) {
    return 'Email o contraseña incorrectos.'
  }
  if (error.code === 'email_not_confirmed') {
    return 'Tu email aún no está confirmado. Usa el enlace de la invitación.'
  }
  if (isRateLimit(error)) return RATE_LIMIT_MESSAGE
  return 'No pudimos iniciar sesión. Inténtalo de nuevo.'
}

/** Traduce errores de updateUser({ password }). */
export function passwordErrorMessage(error: AuthErrorLike): string {
  if (error.code === 'weak_password') {
    return 'La contraseña es demasiado débil. Usa al menos 8 caracteres, mejor con letras y números.'
  }
  if (error.code === 'same_password') {
    return 'La contraseña nueva debe ser distinta de la actual.'
  }
  if (error.code === 'reauthentication_needed') {
    return 'Por seguridad, vuelve a entrar para cambiar tu contraseña.'
  }
  if (
    error.status === 401 ||
    error.code === 'session_not_found' ||
    error.code === 'not_authenticated'
  ) {
    return 'Tu sesión caducó. Solicita un enlace nuevo.'
  }
  if (isRateLimit(error)) return RATE_LIMIT_MESSAGE
  return 'No pudimos guardar la contraseña. Inténtalo de nuevo.'
}
