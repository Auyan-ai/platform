'use client'

import { Suspense, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { createClient } from '@/lib/supabase/client'
import { fetchCurrentUser } from '@/lib/api/users'
import { landingPathFor } from '@/lib/auth/access'
import { passwordErrorMessage } from '@/lib/auth/messages'
import { clearPasswordRequiredCookie, validateNewPassword } from '@/lib/auth/password'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

type Mode = 'recovery' | 'invite' | 'magic'

const COPY: Record<Mode, { title: string; subtitle: string }> = {
  recovery: {
    title: 'Elige tu nueva contraseña',
    subtitle: 'Debes fijarla para volver a entrar al dashboard.',
  },
  invite: {
    title: 'Fija tu contraseña',
    subtitle: 'Así podrás entrar siempre con tu email y contraseña.',
  },
  magic: {
    title: 'Fija una contraseña',
    subtitle: 'Opcional: te permite entrar sin esperar un correo.',
  },
}

function SetPasswordForm() {
  const router = useRouter()
  const params = useSearchParams()
  const rawMode = params.get('mode')
  const mode: Mode = rawMode === 'invite' || rawMode === 'magic' ? rawMode : 'recovery'
  const skippable = mode === 'magic'

  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function goToLanding() {
    const supabase = createClient()
    const {
      data: { session },
    } = await supabase.auth.getSession()
    const user = session?.access_token ? await fetchCurrentUser(session.access_token) : null
    router.push(landingPathFor(user))
    router.refresh()
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)

    const validationError = validateNewPassword(password, confirm)
    if (validationError) {
      setError(validationError)
      return
    }

    setLoading(true)
    const supabase = createClient()
    const { error: updateError } = await supabase.auth.updateUser({
      password,
      data: { password_set: true },
    })
    if (updateError) {
      setError(passwordErrorMessage(updateError))
      setLoading(false)
      return
    }

    clearPasswordRequiredCookie()
    await goToLanding()
  }

  async function handleSkip() {
    setLoading(true)
    const supabase = createClient()
    // Recordamos la decisión para no volver a ofrecerlo en cada enlace de acceso.
    await supabase.auth.updateUser({ data: { password_prompt_dismissed: true } })
    await goToLanding()
  }

  return (
    <Card className="w-full max-w-sm p-8">
      <div className="mb-6">
        <h1 className="text-lg font-semibold text-foreground">{COPY[mode].title}</h1>
        <p className="mt-1 text-sm text-foreground-muted">{COPY[mode].subtitle}</p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="new-password">Contraseña nueva</Label>
          <Input
            id="new-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="new-password"
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="confirm-password">Repite la contraseña</Label>
          <Input
            id="confirm-password"
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
            autoComplete="new-password"
          />
        </div>

        {error && (
          <div
            role="alert"
            className="rounded-sm bg-danger-subtle px-3 py-2 text-sm text-danger-foreground"
          >
            {error}
          </div>
        )}

        <Button type="submit" disabled={loading} className="w-full">
          {loading ? 'Guardando…' : 'Guardar contraseña'}
        </Button>

        {skippable && (
          <Button
            type="button"
            variant="ghost"
            disabled={loading}
            onClick={handleSkip}
            className="w-full"
          >
            Ahora no
          </Button>
        )}
      </form>
    </Card>
  )
}

export default function SetPasswordPage() {
  return (
    <Suspense>
      <SetPasswordForm />
    </Suspense>
  )
}
