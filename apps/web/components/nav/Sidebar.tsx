'use client'

import { cn } from '@/lib/utils'
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useState } from 'react'
import { SidebarAccountMenu } from './SidebarAccountMenu'
import { TenantSwitcher } from './TenantSwitcher'
import { TENANT_NAV_GROUPS } from './nav-items'

interface SidebarProps {
  userEmail?: string
  collapsed: boolean
  onCollapsedChange: (collapsed: boolean) => void
}

export function Sidebar({ userEmail, collapsed, onCollapsedChange }: SidebarProps) {
  const pathname = usePathname()
  const [hovered, setHovered] = useState(false)
  const [suppressHoverPreview, setSuppressHoverPreview] = useState(false)
  const tenantMatch = pathname.match(/\/tenants\/([^/]+)/)
  const activeTenantId = tenantMatch?.[1] ?? null
  const expanded = !collapsed || (hovered && !suppressHoverPreview)

  function handlePointerEnter() {
    if (!suppressHoverPreview) {
      setHovered(true)
    }
  }

  function handlePointerLeave() {
    setHovered(false)
    setSuppressHoverPreview(false)
  }

  function toggleCollapsed() {
    const nextCollapsed = !collapsed
    if (nextCollapsed) {
      setHovered(false)
      setSuppressHoverPreview(true)
    } else {
      setSuppressHoverPreview(false)
    }
    onCollapsedChange(nextCollapsed)
  }

  return (
    <aside
      className={cn(
        'fixed inset-y-0 left-0 z-50 flex flex-col border-r border-border bg-surface-muted transition-[width] duration-200 ease-out',
        expanded ? 'w-[236px]' : 'w-[60px]',
      )}
      onMouseEnter={handlePointerEnter}
      onMouseLeave={handlePointerLeave}
    >
      <div
        className={cn(
          'flex h-14 items-center px-3 transition-[gap,padding] duration-200',
          expanded ? 'gap-2 px-4' : 'justify-center px-2',
        )}
      >
        <span
          className={cn(
            'truncate text-sm font-semibold tracking-tight text-foreground transition-[opacity,width] duration-200',
            expanded
              ? 'min-w-0 flex-1 opacity-100'
              : 'pointer-events-none w-0 flex-none overflow-hidden opacity-0',
          )}
        >
          Auyan
        </span>
        <button
          type="button"
          onClick={toggleCollapsed}
          className="grid size-8 shrink-0 place-items-center rounded-sm text-foreground-muted transition-colors hover:bg-border-subtle hover:text-foreground"
          aria-label={collapsed ? 'Expandir navegación' : 'Replegar navegación'}
          title={collapsed ? 'Expandir navegación' : 'Replegar navegación'}
        >
          {collapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
        </button>
      </div>

      <div className="px-2 pb-2">
        <p
          className={cn(
            'px-2 text-[11px] font-medium uppercase tracking-wider text-foreground-muted transition-[height,margin,opacity] duration-200',
            expanded ? 'mb-1 h-4 opacity-100' : 'mb-0 h-0 overflow-hidden opacity-0',
          )}
        >
          Tenant
        </p>
        <TenantSwitcher activeTenantId={activeTenantId} expanded={expanded} />
      </div>

      <nav className="flex-1 overflow-y-auto px-2 pb-2 text-sm">
        {activeTenantId &&
          TENANT_NAV_GROUPS.map((group) => (
            <div key={group.label} className={cn(expanded ? 'mt-3 first:mt-1' : 'mt-2')}>
              <p
                className={cn(
                  'px-2 text-[10px] font-medium uppercase tracking-normal text-foreground-subtle transition-[height,opacity,padding] duration-200',
                  expanded ? 'h-5 pb-0.5 opacity-100' : 'h-0 overflow-hidden pb-0 opacity-0',
                )}
              >
                {group.label}
              </p>
              <div className="space-y-0.5">
                {group.items.map(({ label, icon: Icon, section }) => {
                  const href = `/tenants/${activeTenantId}/${section}`
                  const isActive = pathname.startsWith(href)
                  return (
                    <Link
                      key={section}
                      href={href}
                      title={expanded ? undefined : label}
                      className={cn(
                        'flex h-8 items-center rounded-sm transition-colors',
                        expanded ? 'gap-2.5 px-2' : 'justify-center px-0',
                        isActive
                          ? 'bg-border-subtle font-medium text-foreground'
                          : 'text-foreground-body hover:bg-border-subtle hover:text-foreground',
                      )}
                    >
                      <Icon className="size-3.5 shrink-0 text-foreground-muted" />
                      <span
                        className={cn(
                          'min-w-0 truncate transition-[opacity,transform] duration-200',
                          expanded
                            ? 'opacity-100'
                            : 'pointer-events-none w-0 -translate-x-1 opacity-0',
                        )}
                      >
                        {label}
                      </span>
                    </Link>
                  )
                })}
              </div>
            </div>
          ))}
      </nav>

      <SidebarAccountMenu email={userEmail} expanded={expanded} />
    </aside>
  )
}
