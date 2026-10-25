'use client'

import { useAdminTenants } from '@/lib/api/hooks/tenants'
import { demoBadgeLabel, isDemo } from '@/lib/demo'
import { cn } from '@/lib/utils'
import type { components } from '@auyan/shared/api-types'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { usePathname, useRouter } from 'next/navigation'
import { useState } from 'react'
import { getTenantSectionFromPath } from './nav-items'

type TenantResponse = components['schemas']['TenantResponse']

const STATUS_DOT: Record<string, string> = {
  active: 'bg-success',
  inactive: 'bg-border-strong',
  suspended: 'bg-danger',
}

interface TenantSwitcherProps {
  activeTenantId: string | null
  expanded?: boolean
}

function tenantInitial(name?: string) {
  return name?.trim().charAt(0).toUpperCase() || 'T'
}

export function TenantSwitcher({ activeTenantId, expanded = true }: TenantSwitcherProps) {
  const [open, setOpen] = useState(false)
  const router = useRouter()
  const pathname = usePathname()
  const { data: tenants, isLoading } = useAdminTenants()

  const active = tenants?.find((t) => t.id === activeTenantId)

  function selectTenant(tenant: TenantResponse) {
    setOpen(false)
    const section = getTenantSectionFromPath(pathname)
    router.push(`/tenants/${tenant.id}/${section}`)
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={cn(
          'flex h-9 w-full items-center rounded-sm text-left text-sm transition-colors hover:bg-border-subtle',
          expanded ? 'gap-2 px-2' : 'justify-center px-0',
        )}
        title={expanded ? undefined : (active?.name ?? 'Selecciona tenant')}
      >
        <span
          className={cn(
            'grid size-6 shrink-0 place-items-center rounded-sm bg-surface text-[11px] font-semibold text-foreground-body ring-1 ring-border-subtle',
            active?.status === 'active' && 'text-success-foreground',
          )}
        >
          {isLoading ? '...' : tenantInitial(active?.name)}
        </span>
        <span
          className={cn(
            'truncate font-medium text-foreground-body transition-[opacity,width] duration-200',
            expanded
              ? 'min-w-0 flex-1 opacity-100'
              : 'pointer-events-none w-0 flex-none overflow-hidden opacity-0',
          )}
        >
          {isLoading ? '…' : (active?.name ?? 'Selecciona tenant')}
        </span>
        <span
          className={cn(
            'transition-[opacity,width] duration-200',
            expanded
              ? 'opacity-100'
              : 'pointer-events-none w-0 flex-none overflow-hidden opacity-0',
          )}
        >
          {open ? (
            <ChevronUp className="size-3.5 text-foreground-subtle" />
          ) : (
            <ChevronDown className="size-3.5 text-foreground-subtle" />
          )}
        </span>
      </button>

      {open && expanded && tenants && (
        <div className="absolute left-0 right-0 top-full z-50 mt-1 rounded-md border border-border bg-surface-elevated shadow-sm overflow-hidden">
          {tenants.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => selectTenant(t)}
              className={cn(
                'w-full flex items-center gap-2 px-3 py-2 text-sm text-left hover:bg-surface-muted transition-colors',
                t.id === activeTenantId && 'bg-surface-muted font-medium text-foreground',
              )}
            >
              <span
                className={cn(
                  'shrink-0 h-1.5 w-1.5 rounded-full',
                  STATUS_DOT[t.status] ?? 'bg-border-strong',
                )}
                aria-label={t.status}
              />
              <span className="min-w-0 flex-1 truncate text-foreground-body">{t.name}</span>
              {isDemo(t) && (
                <span className="shrink-0 text-[11px] text-warning-foreground">
                  {demoBadgeLabel(t.demo_expires_at)}
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
