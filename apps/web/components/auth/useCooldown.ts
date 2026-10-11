import { useEffect, useState } from 'react'
import { cooldownRemaining } from '@/lib/auth/resend'

/** Cuenta atrás (segundos) desde `startedAt`; se detiene sola al llegar a 0. */
export function useCooldown(startedAt: number | null): number {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (startedAt === null) return
    setNow(Date.now())
    const id = setInterval(() => {
      const current = Date.now()
      setNow(current)
      if (cooldownRemaining(startedAt, current) === 0) clearInterval(id)
    }, 500)
    return () => clearInterval(id)
  }, [startedAt])

  return startedAt === null ? 0 : cooldownRemaining(startedAt, now)
}
