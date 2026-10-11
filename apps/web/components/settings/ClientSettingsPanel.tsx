'use client'

import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useMyTenant, useMyTenantConfig } from '@/lib/api/hooks/tenants'
import type { components } from '@auyan/shared/api-types'
import { Bot, Palette, PlugZap, UserRoundCheck } from 'lucide-react'

type IntegrationGroup = components['schemas']['IntegrationGroup']

const KIND_LABELS: Record<IntegrationGroup['kind'], string> = {
  channel: 'Canales',
  helpdesk: 'Helpdesk',
  commerce: 'Tienda',
  llm: 'Modelo',
}

const PROVIDER_LABELS: Record<string, string> = {
  whatsapp: 'WhatsApp',
  chat: 'Chat',
  widget: 'Widget',
  email: 'Email',
  instagram: 'Instagram',
  zendesk: 'Zendesk',
  gorgias: 'Gorgias',
  intercom: 'Intercom',
  chatwoot: 'Chatwoot',
  shopify: 'Shopify',
}

function providerLabel(provider: string) {
  return PROVIDER_LABELS[provider] ?? provider.charAt(0).toUpperCase() + provider.slice(1)
}

function textFromExtra(extra: Record<string, unknown>, keys: string[], fallback: string) {
  for (const key of keys) {
    const value = extra[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return fallback
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wider text-foreground-muted">{label}</p>
      <p className="mt-1 text-sm font-medium text-foreground">{value}</p>
    </div>
  )
}

export function ClientSettingsPanel() {
  const tenant = useMyTenant()
  const config = useMyTenantConfig()

  if (tenant.isLoading || config.isLoading) {
    return (
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-40" />
        <Skeleton className="h-40" />
        <Skeleton className="h-40" />
      </div>
    )
  }

  if (tenant.isError || config.isError || !tenant.data || !config.data) {
    return (
      <div className="rounded-md bg-danger-subtle px-4 py-3 text-sm text-danger-foreground">
        No se pudo cargar la configuración.
      </div>
    )
  }

  const extra = config.data.extra
  const branding = config.data.branding
  const aideName = textFromExtra(
    extra,
    ['assigned_aide_name', 'aide_name'],
    'Contacto asignado por Auyan',
  )
  const aideEmail = textFromExtra(
    extra,
    ['assigned_aide_email', 'aide_email'],
    'Contacto por email semanal',
  )
  const brandName = textFromExtra(branding, ['name', 'brand_name'], tenant.data.name)
  const primaryColor = textFromExtra(branding, ['primary_color', 'accent_color'], 'Mercury light')

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="p-(--density-card-p)">
        <div className="flex items-center gap-2">
          <div className="grid size-8 place-items-center rounded-md bg-surface-muted">
            <PlugZap className="size-4 text-foreground-muted" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-foreground">Integraciones</h2>
            <p className="text-xs text-foreground-muted">
              Estado visible, credenciales gestionadas por Auyan.
            </p>
          </div>
        </div>

        {config.data.integrations.length > 0 ? (
          <div className="mt-4 space-y-3">
            {config.data.integrations.map((group) => (
              <div key={group.kind} className="flex flex-wrap items-center gap-2">
                <p className="w-20 text-xs font-medium uppercase tracking-wider text-foreground-muted">
                  {KIND_LABELS[group.kind]}
                </p>
                {group.integrations.map((integration) => (
                  <Badge key={integration.provider} variant="success">
                    {providerLabel(integration.provider)}
                  </Badge>
                ))}
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-4">
            <Badge variant="muted">Sin integraciones activas</Badge>
          </div>
        )}
      </Card>

      <Card className="p-(--density-card-p)">
        <div className="flex items-center gap-2">
          <div className="grid size-8 place-items-center rounded-md bg-surface-muted">
            <Palette className="size-4 text-foreground-muted" />
          </div>
          <h2 className="text-sm font-semibold text-foreground">Branding</h2>
        </div>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <Field label="Marca" value={brandName} />
          <Field label="Color principal" value={primaryColor} />
        </div>
      </Card>

      <Card className="p-(--density-card-p)">
        <div className="flex items-center gap-2">
          <div className="grid size-8 place-items-center rounded-md bg-surface-muted">
            <UserRoundCheck className="size-4 text-foreground-muted" />
          </div>
          <h2 className="text-sm font-semibold text-foreground">Contacto asignado</h2>
        </div>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <Field label="Responsable" value={aideName} />
          <Field label="Contacto" value={aideEmail} />
        </div>
      </Card>

      <Card className="p-(--density-card-p)">
        <div className="flex items-center gap-2">
          <div className="grid size-8 place-items-center rounded-md bg-surface-muted">
            <Bot className="size-4 text-foreground-muted" />
          </div>
          <h2 className="text-sm font-semibold text-foreground">Agente IA</h2>
        </div>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <Field label="Modelo" value={config.data.agent_model} />
          <Field
            label="Umbral de escalación"
            value={`${Math.round(config.data.escalation_threshold * 100)}%`}
          />
        </div>
      </Card>
    </div>
  )
}
