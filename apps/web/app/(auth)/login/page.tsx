'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { createClient } from '@/lib/supabase/client'
import { fetchCurrentUser } from '@/lib/api/users'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

export default function LoginPage() {
  const router = useRouter()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  // Magic link / invite: Supabase devuelve la sesión en el hash de la URL
  // (#access_token=...&refresh_token=...). El server nunca ve el fragment, así que
  // hay que establecerla en el cliente para que escriba las cookies que lee el layout.
  useEffect(() => {
    const hash = window.location.hash.slice(1)
    if (!hash) return
    const params = new URLSearchParams(hash)

    const errorDescription = params.get('error_description')
    if (errorDescription) {
      setError(errorDescription)
      window.history.replaceState(null, '', window.location.pathname)
      return
    }

    const accessToken = params.get('access_token')
    const refreshToken = params.get('refresh_token')
    if (!accessToken || !refreshToken) return

    setLoading(true)
    const supabase = createClient()
    supabase.auth
      .setSession({ access_token: accessToken, refresh_token: refreshToken })
      .then(async ({ error: sessionError }) => {
        window.history.replaceState(null, '', window.location.pathname)
        if (sessionError) {
          setError(sessionError.message)
          setLoading(false)
          return
        }
        await routeByRole(accessToken)
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function routeByRole(token: string) {
    try {
      const user = await Promise.race([
        fetchCurrentUser(token),
        new Promise<null>((resolve) => setTimeout(() => resolve(null), 5000)),
      ])
      if (user?.role === 'tenant_admin' && user.tenant_id) {
        router.push(`/clients/${user.tenant_id}/overview`)
        return
      }
    } catch {
      // silently fall through to dashboard
    }
    router.push('/')
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError(null)

    const supabase = createClient()
    const { data, error: signInError } = await supabase.auth.signInWithPassword({
      email,
      password,
    })

    if (signInError) {
      setError(signInError.message)
      setLoading(false)
      return
    }

    const token = data.session?.access_token
    if (token) {
      await routeByRole(token)
      return
    }

    router.push('/')
  }

  return (
    <Card className="w-full max-w-sm p-8">
      <div className="mb-6">
        <h1 className="text-lg font-semibold text-foreground">Auyan</h1>
        <p className="mt-1 text-sm text-foreground-muted">
          Accede al dashboard de operaciones
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="email"
            placeholder="agente@auyan.ai"
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="password">Contraseña</Label>
          <Input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="current-password"
          />
        </div>

        {error && (
          <div className="rounded-sm bg-danger-subtle px-3 py-2 text-sm text-danger-foreground">
            {error}
          </div>
        )}

        <Button type="submit" disabled={loading} className="w-full">
          {loading ? 'Entrando…' : 'Entrar'}
        </Button>
      </form>
    </Card>
  )
}
