'use client'

import { Check, Circle } from 'lucide-react'
import { useTenantOnboardingChecklist } from '@/lib/api/hooks/tenant-context'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

const ITEMS: Array<{ key: 'onboarding_submitted' | 'has_commerce_integration' | 'has_helpdesk_integration' | 'has_knowledge'; label: string }> = [
  { key: 'onboarding_submitted', label: 'Onboarding enviado' },
  { key: 'has_commerce_integration', label: 'Conexión comercio (Shopify)' },
  { key: 'has_helpdesk_integration', label: 'Conexión helpdesk (Chatwoot)' },
  { key: 'has_knowledge', label: 'Knowledge base inicial' },
]

const LIFECYCLE_LABELS: Record<string, { label: string; variant: 'default' | 'success' | 'warning' | 'secondary' }> = {
  initial: { label: 'Initial', variant: 'secondary' },
  discovery: { label: 'Discovery', variant: 'warning' },
  building: { label: 'Building', variant: 'default' },
  shadow: { label: 'Shadow', variant: 'default' },
  ramping: { label: 'Ramping', variant: 'default' },
  active: { label: 'Active', variant: 'success' },
  paused: { label: 'Paused', variant: 'secondary' },
  churned: { label: 'Churned', variant: 'secondary' },
}

export function OnboardingChecklistBanner({ tenantId }: { tenantId: string }) {
  const { data, isLoading } = useTenantOnboardingChecklist(tenantId)

  if (isLoading) return <Skeleton className="h-24 w-full" />
  if (!data) return null

  const lifecycle = LIFECYCLE_LABELS[data.agent_lifecycle_state] ?? {
    label: data.agent_lifecycle_state,
    variant: 'secondary' as const,
  }

  return (
    <div className="rounded-md border border-border-subtle bg-surface-muted px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium uppercase tracking-wider text-foreground-muted">
            Checklist discovery → building
          </span>
          <Badge variant={lifecycle.variant}>{lifecycle.label}</Badge>
          {data.is_complete && <Badge variant="success">Listo para AIDE</Badge>}
        </div>
      </div>
      <ul className="mt-3 grid gap-1.5 sm:grid-cols-2">
        {ITEMS.map((item) => {
          const done = Boolean(data[item.key])
          return (
            <li
              key={item.key}
              className={cn(
                'flex items-center gap-2 text-sm',
                done ? 'text-foreground' : 'text-foreground-muted',
              )}
            >
              {done ? (
                <span className="flex size-4 shrink-0 items-center justify-center rounded-full bg-success-subtle text-success-foreground">
                  <Check className="size-3" />
                </span>
              ) : (
                <Circle className="size-4 shrink-0 text-foreground-muted" />
              )}
              {item.label}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
