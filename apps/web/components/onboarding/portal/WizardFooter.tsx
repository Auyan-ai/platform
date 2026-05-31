'use client'

import { createClient } from '@/lib/supabase/client'
import { useRouter } from 'next/navigation'

interface WizardFooterProps {
  userEmail: string
}

/**
 * Footer minimalista del portal.
 * Sesión de [email] + "Cerrar sesión" (no "Usar otro email" — la sesión está
 * atada al magic link del tenant, cambiar email = perder el tenant).
 */
export function WizardFooter({ userEmail }: WizardFooterProps) {
  const router = useRouter()

  async function logout() {
    const supabase = createClient()
    await supabase.auth.signOut()
    router.push('/login')
  }

  return (
    <footer className="pb-6 pt-2 text-center text-xs">
      <div className="text-foreground-subtle">
        Sesión de <span className="text-foreground-muted">{userEmail}</span>
      </div>
      <button
        type="button"
        onClick={logout}
        className="mt-1 cursor-pointer text-foreground-muted hover:text-foreground-body"
      >
        Cerrar sesión
      </button>
    </footer>
  )
}
