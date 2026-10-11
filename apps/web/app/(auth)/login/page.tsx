'use client'

import { Suspense, useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { createClient } from '@/lib/supabase/client'
import { fetchCurrentUser } from '@/lib/api/users'
import { decideMagicAccess, landingPathFor } from '@/lib/auth/access'
import { SET_PASSWORD_PATH } from '@/lib/auth/constants'
import {
  LINK_SENT_MESSAGE,
  RATE_LIMIT_MESSAGE,
  isRateLimit,
  loginErrorMessage,
  signInErrorMessage,
} from '@/lib/auth/messages'
import { setPasswordRequiredCookie } from '@/lib/auth/password'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

function LoginForm() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [mode, setMode] = useState<'password' | 'forgot'>('password')
  const [error, setError] = useState<string | null>(() =>
    loginErrorMessage(searchParams.get('error')),
  )
  const [notice, setNotice] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  // Invitación (y enlaces generados por el API): Supabase devuelve la sesión en el hash de la URL
  // (#access_token=...&refresh_token=...&type=invite). El server nunca ve el fragment, así que
  // hay que establecerla en el cliente para que escriba las cookies que lee el layout.
  useEffect(() => {
    const hash = window.location.hash.slice(1)
    if (!hash) return
    const params = new URLSearchParams(hash)

    if (params.get('error_description') || params.get('error')) {
      setError(
        loginErrorMessage(
          params.get('error_code') === 'otp_expired' ? 'link_expired' : 'link_invalid',
        ),
      )
      window.history.replaceState(null, '', window.location.pathname)
      return
    }

    const accessToken = params.get('access_token')
    const refreshToken = params.get('refresh_token')
    if (!accessToken || !refreshToken) return
    const linkType = params.get('type')

    setLoading(true)
    const supabase = createClient()
    supabase.auth
      .setSession({ access_token: accessToken, refresh_token: refreshToken })
      .then(async ({ error: sessionError }) => {
        window.history.replaceState(null, '', window.location.pathname)
        if (sessionError) {
          setError(loginErrorMessage('link_invalid'))
          setLoading(false)
          return
        }
        await handleLinkSession(accessToken, linkType)
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function handleLinkSession(token: string, linkType: string | null) {
    if (linkType === 'recovery') {
      setPasswordRequiredCookie()
      router.push(`${SET_PASSWORD_PATH}?mode=recovery`)
      return
    }

    // Invitación o enlace de acceso: solo tenant_admin (mismo criterio que el callback).
    const access = decideMagicAccess(await fetchCurrentUser(token))
    if (!access.ok) {
      await createClient().auth.signOut()
      setError(loginErrorMessage(access.error))
      setLoading(false)
      return
    }
    if (linkType === 'invite') {
      setPasswordRequiredCookie()
      router.push(`${SET_PASSWORD_PATH}?mode=invite`)
      return
    }
    // Enlace de acceso (p. ej. el que manda el API a un usuario ya existente): si aún no decidió
    // sobre la contraseña, se le ofrece fijarla (saltable).
    const { data } = await createClient().auth.getUser()
    const meta = data.user?.user_metadata ?? {}
    if (meta.password_set !== true && meta.password_prompt_dismissed !== true) {
      router.push(`${SET_PASSWORD_PATH}?mode=magic`)
      return
    }
    router.push(access.landing)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    setNotice(null)

    const supabase = createClient()
    const { data, error: signInError } = await supabase.auth.signInWithPassword({
      email,
      password,
    })

    if (signInError) {
      setError(signInErrorMessage(signInError))
      setLoading(false)
      return
    }

    const token = data.session?.access_token
    const user = token ? await fetchCurrentUser(token) : null
    router.push(landingPathFor(user))
    router.refresh()
  }

  async function requestLink(kind: 'magic' | 'reset') {
    setError(null)
    setNotice(null)
    if (!email.trim()) {
      setError('Escribe tu email primero.')
      return
    }
    setLoading(true)
    const supabase = createClient()
    const origin = window.location.origin
    const { error: linkError } =
      kind === 'magic'
        ? await supabase.auth.signInWithOtp({
            email,
            options: { shouldCreateUser: false, emailRedirectTo: `${origin}/auth/callback` },
          })
        : await supabase.auth.resetPasswordForEmail(email, {
            redirectTo: `${origin}/auth/callback?flow=recovery`,
          })
    setLoading(false)
    // Respuesta idéntica exista o no el email; solo se distingue el rate limit.
    if (isRateLimit(linkError)) {
      setError(RATE_LIMIT_MESSAGE)
      return
    }
    setNotice(LINK_SENT_MESSAGE)
  }

  function switchMode(next: 'password' | 'forgot') {
    setMode(next)
    setError(null)
    setNotice(null)
  }

  const forgot = mode === 'forgot'

  return (
    <Card className="w-full max-w-sm p-8">
      <div className="mb-6">
        <h1 className="text-lg font-semibold text-foreground">Auyan</h1>
        <p className="mt-1 text-sm text-foreground-muted">
          {forgot ? 'Recupera el acceso a tu cuenta' : 'Accede al dashboard de operaciones'}
        </p>
      </div>

      <form
        onSubmit={
          forgot
            ? (e) => {
                e.preventDefault()
                void requestLink('reset')
              }
            : handleSubmit
        }
        className="space-y-4"
      >
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

        {!forgot && (
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
        )}

        {error && (
          <div
            role="alert"
            className="rounded-sm bg-danger-subtle px-3 py-2 text-sm text-danger-foreground"
          >
            {error}
          </div>
        )}
        {notice && (
          <output className="block rounded-sm bg-surface-muted px-3 py-2 text-sm text-foreground-body">
            {notice}
          </output>
        )}

        {forgot ? (
          <>
            <Button type="submit" disabled={loading} className="w-full">
              {loading ? 'Enviando…' : 'Enviar enlace de recuperación'}
            </Button>
            <Button
              type="button"
              variant="ghost"
              className="w-full"
              onClick={() => switchMode('password')}
            >
              Volver a entrar
            </Button>
          </>
        ) : (
          <>
            <Button type="submit" disabled={loading} className="w-full">
              {loading ? 'Entrando…' : 'Entrar'}
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={loading}
              className="w-full"
              onClick={() => void requestLink('magic')}
            >
              Recibir enlace de acceso
            </Button>
            <Button
              type="button"
              variant="link"
              className="w-full"
              onClick={() => switchMode('forgot')}
            >
              ¿Olvidaste tu contraseña?
            </Button>
          </>
        )}
      </form>
    </Card>
  )
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  )
}
