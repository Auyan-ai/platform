'use client'

import { Check, Circle } from 'lucide-react'
import { useTenantOnboardingChecklist } from '@/lib/api/hooks/tenant-context'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

const ITEMS: Array<{
  key:
    | 'onboarding_submitted'
    | 'has_commerce_integration'
    | 'has_helpdesk_integration'
    | 'has_knowledge'
  label: string
}> = [
  { key: 'onboarding_submitted', label: 'Información inicial enviada' },
  { key: 'has_commerce_integration', label: 'Conexión comercio (Shopify)' },
  { key: 'has_helpdesk_integration', label: 'Conexión helpdesk (Chatwoot)' },
  { key: 'has_knowledge', label: 'Base de conocimiento inicial' },
]

const LIFECYCLE_LABELS: Record<
  string,
  { label: string; variant: 'default' | 'success' | 'warning' | 'secondary' }
> = {
  initial: { label: 'Inicial', variant: 'secondary' },
  discovery: { label: 'Preparación', variant: 'warning' },
  building: { label: 'Construcción', variant: 'default' },
  shadow: { label: 'Modo shadow', variant: 'default' },
  ramping: { label: 'Rampa', variant: 'default' },
  active: { label: 'Activo', variant: 'success' },
  paused: { label: 'Pausado', variant: 'secondary' },
  churned: { label: 'Cerrado', variant: 'secondary' },
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
            Checklist de activación
          </span>
          <Badge variant={lifecycle.variant}>{lifecycle.label}</Badge>
          {data.complete && <Badge variant="success">Listo para revisión</Badge>}
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
