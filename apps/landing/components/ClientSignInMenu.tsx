'use client'

import { ChevronDown, LogIn } from 'lucide-react'
import Link from 'next/link'
import { useEffect, useRef, useState } from 'react'

const appUrl = (process.env.NEXT_PUBLIC_APP_URL ?? 'http://localhost:3000').replace(/\/$/, '')
const loginHref = `${appUrl}/login`

export function ClientSignInMenu() {
  const [open, setOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return

    function handlePointerDown(event: PointerEvent) {
      if (!menuRef.current?.contains(event.target as Node)) {
        setOpen(false)
      }
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setOpen(false)
      }
    }

    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [open])

  return (
    <div ref={menuRef} className="relative">
      <button
        type="button"
        className="inline-flex h-9 items-center gap-1.5 rounded-full border border-border bg-surface px-3 text-sm font-medium text-foreground transition-colors hover:border-border-strong hover:bg-surface-muted"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        Sign in
        <ChevronDown
          className={`size-4 text-foreground-muted transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 top-11 w-64 rounded-lg border border-border bg-surface-elevated p-2 text-sm shadow-[0_12px_32px_rgba(28,25,23,0.12)]"
        >
          <Link
            role="menuitem"
            href={loginHref}
            className="flex items-start gap-3 rounded-md px-3 py-3 transition-colors hover:bg-surface-muted focus:bg-surface-muted"
            onClick={() => setOpen(false)}
          >
            <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-full bg-accent-subtle text-accent-foreground">
              <LogIn className="size-4" />
            </span>
            <span>
              <span className="block font-medium text-foreground">Portal cliente</span>
              <span className="mt-0.5 block text-xs leading-5 text-foreground-muted">
                Entra al dashboard de Auyan con tu invitación.
              </span>
            </span>
          </Link>
        </div>
      )}
    </div>
  )
}
