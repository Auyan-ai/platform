import { MIN_PASSWORD_LENGTH, PASSWORD_REQUIRED_COOKIE } from './constants'

/** Valida contraseña nueva + confirmación. Devuelve el mensaje de error o null si es válida. */
export function validateNewPassword(password: string, confirm: string): string | null {
  if (password.length < MIN_PASSWORD_LENGTH) {
    return `La contraseña debe tener al menos ${MIN_PASSWORD_LENGTH} caracteres.`
  }
  if (password !== confirm) return 'Las contraseñas no coinciden.'
  return null
}

/** Marca (en el navegador) que hay que fijar contraseña antes de entrar al dashboard. */
export function setPasswordRequiredCookie(): void {
  const secure = window.location.protocol === 'https:' ? '; Secure' : ''
  document.cookie = `${PASSWORD_REQUIRED_COOKIE}=1; Path=/; Max-Age=3600; SameSite=Lax${secure}`
}

export function clearPasswordRequiredCookie(): void {
  document.cookie = `${PASSWORD_REQUIRED_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax`
}
