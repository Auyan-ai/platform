/** Intervalo mínimo entre envíos al mismo email que impone Supabase Auth. */
export const RESEND_COOLDOWN_SECONDS = 60

/** Segundos que faltan para poder reenviar (0 = ya se puede). Función pura para poder probarla. */
export function cooldownRemaining(
  sentAt: number,
  now: number,
  totalSeconds: number = RESEND_COOLDOWN_SECONDS,
): number {
  return Math.max(0, Math.ceil((sentAt + totalSeconds * 1000 - now) / 1000))
}
