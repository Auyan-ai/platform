'use client'

import { Suspense, useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { createClient } from '@/lib/supabase/client'
import { fetchCurrentUser } from '@/lib/api/users'
import { decideMagicAccess, landingPathFor } from '@/lib/auth/access'
import { SET_PASSWORD_PATH } from '@/lib/auth/constants'
import {
  EMAIL_RATE_LIMIT_MESSAGE,
  EMAIL_REQUIRED_MESSAGE,
  isRateLimit,
  loginErrorMessage,
  signInErrorMessage,
} from '@/lib/auth/messages'
import { setPasswordRequiredCookie } from '@/lib/auth/password'
import { Loader2 } from 'lucide-react'
import { AuthCard, AuthError } from '@/components/auth/AuthCard'
import { useCooldown } from '@/components/auth/useCooldown'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

type LinkKind = 'magic' | 'reset'

function LoginForm() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  // 'link' = email primero (enlace de acceso); 'password' = aparece el campo contraseña.
  const [mode, setMode] = useState<'link' | 'password'>('link')
  // Tras pedir enlace o recuperación la tarjeta pasa a "Revisa tu correo".
  const [sent, setSent] = useState<{ kind: LinkKind; email: string; at: number } | null>(null)
  const [error, setError] = useState<string | null>(() =>
    loginErrorMessage(searchParams.get('error')),
  )
  // idle → sending (pidiendo enlace) | entering (contraseña OK; esperando a la API) | verifying (volviendo de un enlace)
  const [phase, setPhase] = useState<'idle' | 'sending' | 'entering' | 'verifying'>('idle')
  const busy = phase !== 'idle'
  const remaining = useCooldown(sent?.at ?? null)

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

    setPhase('verifying')
    const supabase = createClient()
    supabase.auth
      .setSession({ access_token: accessToken, refresh_token: refreshToken })
      .then(async ({ error: sessionError }) => {
        window.history.replaceState(null, '', window.location.pathname)
        if (sessionError) {
          setError(loginErrorMessage('link_invalid'))
          setPhase('idle')
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
      setPhase('idle')
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
    if (busy) return
    if (mode === 'link') {
      await requestLink('magic', email)
      return
    }

    setPhase('entering')
    setError(null)
    const supabase = createClient()
    const { data, error: signInError } = await supabase.auth.signInWithPassword({
      email,
      password,
    })

    if (signInError) {
      setError(signInErrorMessage(signInError))
      setPhase('idle')
      return
    }

    // fetchCurrentUser puede tardar (arranque en frío de la API): se mantiene "Entrando…".
    const token = data.session?.access_token
    const user = token ? await fetchCurrentUser(token) : null
    router.push(landingPathFor(user))
    router.refresh()
  }

  async function requestLink(kind: LinkKind, to: string): Promise<boolean> {
    setError(null)
    const target = to.trim()
    if (!target) {
      setError(EMAIL_REQUIRED_MESSAGE)
      return false
    }
    setPhase('sending')
    const supabase = createClient()
    const origin = window.location.origin
    const { error: linkError } =
      kind === 'magic'
        ? await supabase.auth.signInWithOtp({
            email: target,
            options: { shouldCreateUser: false, emailRedirectTo: `${origin}/auth/callback` },
          })
        : await supabase.auth.resetPasswordForEmail(target, {
            redirectTo: `${origin}/auth/callback?flow=recovery`,
          })
    setPhase('idle')
    // Respuesta idéntica exista o no el email; solo se distingue el rate limit.
    if (isRateLimit(linkError)) {
      setError(EMAIL_RATE_LIMIT_MESSAGE)
      return false
    }
    setSent({ kind, email: target, at: Date.now() })
    return true
  }

  function switchMode(next: 'link' | 'password') {
    setMode(next)
    setError(null)
  }

  if (sent) {
    return (
      <AuthCard
        title="Revisa tu correo"
        description={
          <>
            Si <span className="font-medium text-foreground">{sent.email}</span> tiene cuenta, te
            hemos enviado{' '}
            {sent.kind === 'reset' ? 'un enlace para recuperar tu contraseña' : 'un enlace de acceso'}
            .
          </>
        }
      >
        <div className="space-y-4">
          <p className="rounded-sm bg-surface-muted px-3 py-2 text-sm text-foreground-body">
            Ábrelo en este mismo navegador: si lo abres en otro, no funcionará.
          </p>
          {error && <AuthError>{error}</AuthError>}
          <Button
            type="button"
            variant="outline"
            className="w-full"
            disabled={remaining > 0 || phase === 'sending'}
            onClick={() => void requestLink(sent.kind, sent.email)}
          >
            {phase === 'sending' ? (
              <>
                <Loader2 className="animate-spin" aria-hidden />
                Enviando…
              </>
            ) : remaining > 0 ? (
              `Reenviar en ${remaining} s`
            ) : (
              'Reenviar'
            )}
          </Button>
          <Button
            type="button"
            variant="ghost"
            className="w-full"
            onClick={() => {
              setSent(null)
              setError(null)
            }}
          >
            Usar otro email
          </Button>
        </div>
      </AuthCard>
    )
  }

  // Volviendo de un enlace (hash con sesión): sin formulario, solo el estado de espera.
  if (phase === 'verifying') {
    return (
      <AuthCard title="Entrando…" description="Estamos verificando tu acceso.">
        <output className="flex justify-center py-2" aria-label="Entrando">
          <Loader2 className="size-5 animate-spin text-foreground-muted" aria-hidden />
        </output>
      </AuthCard>
    )
  }

  const passwordMode = mode === 'password'

  return (
    <AuthCard
      title="Bienvenido a Auyan"
      description={
        passwordMode
          ? 'Entra con tu email y contraseña.'
          : 'Escribe tu email y te enviamos un enlace de acceso.'
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            name="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="username"
            autoFocus
            disabled={busy}
            placeholder="tu@empresa.com"
          />
        </div>

        {/*
          El campo contraseña NO está en el DOM en modo enlace: un input oculto lo autorrellenaría
          sin que el usuario lo vea y los gestores lo tratarían como credencial guardable. Al
          montarse al pulsar "Prefiero usar contraseña", el gestor lo detecta como cualquier
          campo dinámico. El contenedor sí existe siempre para animar la altura (grid 0fr→1fr).
        */}
        <div
          className={`grid transition-[grid-template-rows,opacity] duration-200 ease-out motion-reduce:transition-none ${
            passwordMode ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'
          }`}
        >
          <div className="-m-1 overflow-hidden p-1">
            {passwordMode && (
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <Label htmlFor="password">Contraseña</Label>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void requestLink('reset', email)}
                    className="text-xs text-accent underline-offset-4 hover:underline disabled:opacity-50"
                  >
                    ¿Olvidaste tu contraseña?
                  </button>
                </div>
                <Input
                  id="password"
                  name="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  autoComplete="current-password"
                  autoFocus
                  disabled={busy}
                />
              </div>
            )}
          </div>
        </div>

        {error && <AuthError>{error}</AuthError>}

        <Button type="submit" disabled={busy} className="w-full">
          {busy && <Loader2 className="animate-spin" aria-hidden />}
          {phase === 'entering'
            ? 'Entrando…'
            : phase === 'sending'
              ? 'Enviando…'
              : passwordMode
                ? 'Entrar'
                : 'Enviarme un enlace de acceso'}
        </Button>

        <Button
          type="button"
          variant="link"
          disabled={busy}
          className="w-full text-foreground-muted"
          onClick={() => switchMode(passwordMode ? 'link' : 'password')}
        >
          {passwordMode ? 'Prefiero recibir un enlace de acceso' : 'Prefiero usar contraseña'}
        </Button>
      </form>
    </AuthCard>
  )
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  )
}
