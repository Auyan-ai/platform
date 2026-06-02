'use client'

import { ArrowRight, Search } from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useEffect, useMemo, useRef, useState } from 'react'

export interface QuickLink {
  label: string
  href: string
  description?: string
}

interface AppTopbarProps {
  placeholder?: string
  quickLinks?: QuickLink[]
}

function matchesLink(link: QuickLink, query: string) {
  const value = `${link.label} ${link.description ?? ''}`.toLowerCase()
  return value.includes(query.toLowerCase())
}

export function AppTopbar({ placeholder = 'Buscar...', quickLinks = [] }: AppTopbarProps) {
  const router = useRouter()
  const rootRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')

  const filteredLinks = useMemo(() => {
    const value = query.trim()
    if (!value) return quickLinks.slice(0, 6)
    return quickLinks.filter((link) => matchesLink(link, value)).slice(0, 8)
  }, [query, quickLinks])

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

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setOpen(true)
        window.requestAnimationFrame(() => inputRef.current?.focus())
      }

      if (event.key === 'Escape') {
        setOpen(false)
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [])

  function openSearch() {
    setOpen(true)
    window.requestAnimationFrame(() => inputRef.current?.focus())
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const first = filteredLinks[0]
    if (!first) return
    setOpen(false)
    setQuery('')
    router.push(first.href)
  }

  return (
    <header className="flex h-14 items-center gap-4 border-b border-border bg-surface px-6">
      <div ref={rootRef} className="relative min-w-0 flex-1">
        <button
          type="button"
          onClick={openSearch}
          className="flex h-9 w-full min-w-0 items-center gap-3 rounded-sm px-0 py-2 text-left text-sm text-foreground-muted transition-colors hover:text-foreground"
        >
          <Search className="size-3.5 shrink-0" />
          <span className="truncate">{placeholder}</span>
          <kbd className="ml-auto hidden rounded-xs border border-border bg-surface px-1.5 py-0.5 text-[10px] font-medium text-foreground-muted md:inline">
            K
          </kbd>
        </button>

        {open && (
          <div className="absolute left-0 top-11 z-50 w-full max-w-xl overflow-hidden rounded-md border border-border bg-surface-elevated shadow-lg">
            <form
              onSubmit={handleSubmit}
              className="flex items-center gap-2 border-b border-border-subtle px-3 py-2"
            >
              <Search className="size-4 shrink-0 text-foreground-muted" />
              <input
                ref={inputRef}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={placeholder}
                className="h-8 min-w-0 flex-1 bg-transparent text-sm text-foreground placeholder:text-foreground-subtle"
              />
            </form>

            <div className="max-h-80 overflow-y-auto p-1">
              {filteredLinks.length > 0 ? (
                filteredLinks.map((link) => (
                  <Link
                    key={link.href}
                    href={link.href}
                    onClick={() => {
                      setOpen(false)
                      setQuery('')
                    }}
                    className="flex items-center gap-3 rounded-sm px-2 py-2 text-sm text-foreground-body transition-colors hover:bg-surface-muted hover:text-foreground"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">{link.label}</span>
                      {link.description && (
                        <span className="block truncate text-xs text-foreground-muted">
                          {link.description}
                        </span>
                      )}
                    </span>
                    <ArrowRight className="size-3.5 shrink-0 text-foreground-subtle" />
                  </Link>
                ))
              ) : (
                <div className="px-3 py-6 text-center text-sm text-foreground-muted">
                  No hay resultados
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </header>
  )
}
