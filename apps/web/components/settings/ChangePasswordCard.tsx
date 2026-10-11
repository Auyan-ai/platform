'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { passwordErrorMessage } from '@/lib/auth/messages'
import { validateNewPassword } from '@/lib/auth/password'
import { createClient } from '@/lib/supabase/client'

/** Cambio de contraseña con la sesión iniciada. */
export function ChangePasswordCard() {
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setSaved(false)

    const validationError = validateNewPassword(password, confirm)
    if (validationError) {
      setError(validationError)
      return
    }

    setLoading(true)
    const { error: updateError } = await createClient().auth.updateUser({
      password,
      data: { password_set: true },
    })
    setLoading(false)
    if (updateError) {
      setError(passwordErrorMessage(updateError))
      return
    }
    setPassword('')
    setConfirm('')
    setSaved(true)
  }

  return (
    <Card className="max-w-md p-6">
      <h2 className="text-base font-semibold text-foreground">Contraseña</h2>
      <p className="mt-1 text-sm text-foreground-muted">
        Cambia la contraseña con la que entras al dashboard.
      </p>

      <form onSubmit={handleSubmit} className="mt-4 space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="account-new-password">Contraseña nueva</Label>
          <Input
            id="account-new-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="new-password"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="account-confirm-password">Repite la contraseña</Label>
          <Input
            id="account-confirm-password"
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
        {saved && (
          <output className="block rounded-sm bg-success-subtle px-3 py-2 text-sm text-success-foreground">
            Contraseña actualizada.
          </output>
        )}

        <Button type="submit" disabled={loading}>
          {loading ? 'Guardando…' : 'Cambiar contraseña'}
        </Button>
      </form>
    </Card>
  )
}
