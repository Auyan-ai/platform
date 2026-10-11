import { type NextRequest, NextResponse } from 'next/server'
import { createServerClient, type CookieOptions } from '@supabase/ssr'
import { fetchCurrentUser } from '@/lib/api/users'
import { resolveCallback } from '@/lib/auth/callback'
import { PASSWORD_REQUIRED_COOKIE } from '@/lib/auth/constants'

type PendingCookie = { name: string; value: string; options: CookieOptions }

/** Canje del enlace de Supabase Auth (enlace de acceso / recuperación, flujo PKCE). */
export async function GET(request: NextRequest) {
  const pending: PendingCookie[] = []

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll()
        },
        setAll(cookies: PendingCookie[]) {
          pending.push(...cookies)
        },
      },
    },
  )

  const result = await resolveCallback(request.nextUrl.searchParams, {
    async exchangeCode(code) {
      const { data, error } = await supabase.auth.exchangeCodeForSession(code)
      return {
        accessToken: data.session?.access_token ?? null,
        userMetadata: (data.user?.user_metadata ?? {}) as Record<string, unknown>,
        error,
      }
    },
    async signOut() {
      await supabase.auth.signOut()
    },
    fetchUser: fetchCurrentUser,
  })

  const response = NextResponse.redirect(new URL(result.redirectTo, request.nextUrl.origin))
  for (const { name, value, options } of pending) {
    response.cookies.set(name, value, options as Parameters<typeof response.cookies.set>[2])
  }
  if (result.requirePassword) {
    response.cookies.set(PASSWORD_REQUIRED_COOKIE, '1', {
      path: '/',
      sameSite: 'lax',
      maxAge: 60 * 60,
      secure: request.nextUrl.protocol === 'https:',
    })
  }
  return response
}
