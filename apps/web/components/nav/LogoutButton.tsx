'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { LogOut } from 'lucide-react'
import { createClient } from '@/lib/supabase/client'

interface LogoutButtonProps {
  email?: string
}

export function LogoutButton({ email }: LogoutButtonProps) {
  const router = useRouter()
  const [loading, setLoading] = useState(false)

  async function handleLogout() {
    setLoading(true)
    const supabase = createClient()
    await supabase.auth.signOut()
    router.push('/login')
    router.refresh()
  }

  return (
    <div className="border-t border-border-subtle p-2">
      {email && (
        <p className="mb-2 truncate px-2 text-xs text-foreground-muted" title={email}>
          {email}
        </p>
      )}
      <button
        type="button"
        onClick={handleLogout}
        disabled={loading}
        className="flex w-full items-center gap-2.5 rounded-sm px-2 py-1.5 text-sm text-foreground-body transition-colors hover:bg-border-subtle hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
      >
        <LogOut className="size-3.5 shrink-0 text-foreground-muted" />
        <span>{loading ? 'Cerrando…' : 'Cerrar sesión'}</span>
      </button>
    </div>
  )
}
