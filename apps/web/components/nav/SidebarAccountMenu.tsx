'use client'

import { createClient } from '@/lib/supabase/client'
import { cn } from '@/lib/utils'
import { Bell, ChevronDown, LogOut, Settings2, UserCircle } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useEffect, useRef, useState } from 'react'

interface SidebarAccountMenuProps {
  email?: string
  expanded: boolean
}

function getInitial(email?: string) {
  return email?.trim().charAt(0).toUpperCase() || 'A'
}

export function SidebarAccountMenu({ email, expanded }: SidebarAccountMenuProps) {
  const router = useRouter()
  const rootRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open) return

    function handlePointerDown(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false)
      }
    }

    document.addEventListener('mousedown', handlePointerDown)
    return () => document.removeEventListener('mousedown', handlePointerDown)
  }, [open])

  async function handleLogout() {
    setLoading(true)
    const supabase = createClient()
    await supabase.auth.signOut()
    router.push('/login')
    router.refresh()
  }

  return (
    <div ref={rootRef} className="relative border-t border-border-subtle p-2">
      {open && expanded && (
        <div className="absolute bottom-full left-2 z-50 mb-2 w-[220px] overflow-hidden rounded-md border border-border bg-surface-elevated py-1 shadow-lg">
          {email && (
            <div className="truncate px-3 pb-1.5 pt-2 text-xs text-foreground-muted" title={email}>
              {email}
            </div>
          )}

          <button
            type="button"
            disabled
            title="Todavía no hay una página de configuración conectada"
            className="flex w-full cursor-not-allowed items-center gap-2 px-3 py-2 text-left text-sm text-foreground-muted opacity-70"
          >
            <Settings2 className="size-4 shrink-0" />
            <span>Configuración</span>
          </button>
          <button
            type="button"
            disabled
            title="Todavía no hay un centro de notificaciones conectado"
            className="flex w-full cursor-not-allowed items-center gap-2 px-3 py-2 text-left text-sm text-foreground-muted opacity-70"
          >
            <Bell className="size-4 shrink-0" />
            <span>Notificaciones</span>
          </button>

          <div className="my-1 border-t border-border-subtle" />

          <button
            type="button"
            onClick={handleLogout}
            disabled={loading}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-foreground-body transition-colors hover:bg-surface-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
          >
            <LogOut className="size-4 shrink-0" />
            <span>{loading ? 'Cerrando...' : 'Cerrar sesión'}</span>
          </button>
        </div>
      )}

      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className={cn(
          'flex h-10 w-full items-center rounded-sm text-sm text-foreground-body transition-colors hover:bg-border-subtle hover:text-foreground',
          expanded ? 'gap-2 px-2' : 'justify-center px-0',
        )}
        aria-expanded={open}
        aria-label="Abrir menú de cuenta"
        title={expanded ? undefined : 'Cuenta'}
      >
        <span className="grid size-7 shrink-0 place-items-center rounded-full bg-accent-subtle text-[11px] font-semibold text-accent-foreground">
          {email ? getInitial(email) : <UserCircle className="size-4" />}
        </span>
        <span
          className={cn(
            'min-w-0 flex-1 truncate text-left transition-[opacity,transform] duration-200',
            expanded ? 'opacity-100' : 'pointer-events-none opacity-0',
          )}
          title={email}
        >
          {email ?? 'Cuenta'}
        </span>
        <ChevronDown
          className={cn(
            'size-3.5 shrink-0 text-foreground-subtle transition-[opacity,transform] duration-200',
            open && 'rotate-180',
            expanded ? 'opacity-100' : 'opacity-0',
          )}
        />
      </button>
    </div>
  )
}
