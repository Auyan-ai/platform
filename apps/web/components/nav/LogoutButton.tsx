'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'
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
    <div className="border-t border-neutral-100 p-3">
      {email && (
        <p className="mb-2 truncate px-2 text-xs text-neutral-500" title={email}>
          {email}
        </p>
      )}
      <button
        type="button"
        onClick={handleLogout}
        disabled={loading}
        className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-neutral-600 transition-colors hover:bg-neutral-100 hover:text-neutral-900 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <span>↩︎</span>
        <span>{loading ? 'Cerrando...' : 'Cerrar sesión'}</span>
      </button>
    </div>
  )
}
