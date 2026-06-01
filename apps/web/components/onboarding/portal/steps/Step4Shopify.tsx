'use client'

import { useState } from 'react'
import { CheckCircle2 } from 'lucide-react'
import { WizardSplitLayout } from '../WizardLayouts'
import { WizardInput } from '../WizardInput'
import { WizardStepHeader } from '../WizardStepHeader'
import { WizardStepActions } from '../WizardStepActions'
import {
  useConnectShopify,
  useTenantIntegrations,
  type TenantIntegrationStatus,
} from '@/lib/api/hooks/tenant-context'
import type { StepProps } from './types'

const FEATURES = [
  {
    title: 'Estado de pedidos',
    desc: 'Cliente pregunta "¿dónde está mi pedido?" → agente responde con tracking real.',
  },
  {
    title: 'Catálogo y stock',
    desc: 'Disponibilidad, variantes y precios actualizados al minuto.',
  },
  {
    title: 'Devoluciones y políticas',
    desc: 'El agente cita tu política de devolución textualmente, no la inventa.',
  },
]

function findShopify(
  integrations: TenantIntegrationStatus[] | undefined,
): TenantIntegrationStatus | undefined {
  return integrations?.find((i) => i.kind === 'commerce' && i.provider === 'shopify' && i.is_active)
}

export function Step4Shopify({ tenantId, onContinue, onSkip, onBack }: StepProps) {
  const integrationsQuery = useTenantIntegrations(tenantId)
  const connectMutation = useConnectShopify(tenantId)
  const existing = findShopify(integrationsQuery.data?.integrations)

  const [domain, setDomain] = useState('')
  const [clientId, setClientId] = useState('')
  const [clientSecret, setClientSecret] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function connect() {
    setError(null)
    if (!domain.trim() || !clientId.trim() || !clientSecret.trim()) {
      setError('Domain, Client ID y Client Secret son obligatorios.')
      return
    }
    try {
      await connectMutation.mutateAsync({
        domain: domain.trim(),
        client_id: clientId.trim(),
        client_secret: clientSecret.trim(),
      })
      setClientSecret('')
      onContinue()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo conectar Shopify.')
    }
  }

  return (
    <WizardSplitLayout>
      <WizardStepHeader
        title="Conecta Shopify"
        subtitle="Damos al agente acceso de lectura para responder sobre pedidos, productos y devoluciones."
      />

      {existing && (
        <div className="mb-5 flex items-start gap-2 rounded-md border border-success bg-success-subtle px-3 py-2 text-sm text-success-foreground">
          <CheckCircle2 className="size-4 shrink-0" />
          <div>
            <p className="font-medium">Shopify conectado</p>
            <p className="text-xs opacity-80">Dominio: {String(existing.config.domain ?? '—')}</p>
          </div>
        </div>
      )}

      <div className="flex flex-col gap-4">
        {FEATURES.map((f) => (
          <div key={f.title}>
            <div className="mb-0.5 text-[13px] font-medium text-foreground">{f.title}</div>
            <div className="text-[13px] leading-relaxed text-foreground-muted">{f.desc}</div>
          </div>
        ))}
      </div>

      <details className="mt-6 rounded-md bg-surface-muted px-3 py-2 text-[13px] text-foreground-body">
        <summary className="cursor-pointer text-foreground-muted">
          ¿De dónde saco Client ID y Client Secret?
        </summary>
        <p className="mt-2 text-foreground-muted">
          Desde el 1 de enero de 2026, Shopify deprecó los Custom Apps con token
          permanente. Las apps nuevas se crean en el <strong>Dev Dashboard</strong>{' '}
          y usan OAuth Client Credentials (token de 24h, refrescado automáticamente).
        </p>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-foreground-muted">
          <li>
            Entra en{' '}
            <a
              href="https://shopify.dev/dashboard"
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent hover:underline"
            >
              shopify.dev/dashboard
            </a>{' '}
            (o desde tu Shopify admin: Settings → Apps → Develop apps → Build apps).
          </li>
          <li>
            Crea una nueva app, nómbrala <code className="rounded-xs bg-surface px-1 py-0.5">Auyan</code>.
          </li>
          <li>
            En <strong>Configuration → Admin API access scopes</strong> activa:{' '}
            <code className="rounded-xs bg-surface px-1 py-0.5">read_orders</code>,{' '}
            <code className="rounded-xs bg-surface px-1 py-0.5">read_products</code>,{' '}
            <code className="rounded-xs bg-surface px-1 py-0.5">read_customers</code>,{' '}
            <code className="rounded-xs bg-surface px-1 py-0.5">read_content</code>.
          </li>
          <li>
            Instala la app en tu tienda (botón <strong>Install</strong> en el Dev Dashboard).
          </li>
          <li>
            En la sección <strong>Configuration → Client credentials</strong> aparecen{' '}
            <strong>Client ID</strong> y <strong>Client Secret</strong>. Cópialos abajo.
          </li>
        </ol>
        <a
          href="https://shopify.dev/docs/apps/build/authentication-authorization/access-tokens/client-credentials-grant"
          target="_blank"
          rel="noopener noreferrer"
          className="mt-2 inline-block text-accent hover:underline"
        >
          Doc oficial: Client Credentials Grant ↗
        </a>
      </details>

      <div className="mt-4 grid gap-2">
        <WizardInput
          label="Dominio Shopify"
          placeholder="mareastudio.myshopify.com"
          value={domain}
          onChange={(e) => setDomain(e.target.value)}
        />
        <WizardInput
          label="Client ID"
          placeholder="abc123..."
          value={clientId}
          onChange={(e) => setClientId(e.target.value)}
        />
        <WizardInput
          label="Client Secret"
          type="password"
          placeholder="shpss_..."
          value={clientSecret}
          onChange={(e) => setClientSecret(e.target.value)}
        />
      </div>

      {error && <p className="mt-3 text-sm text-danger-foreground">{error}</p>}

      <WizardStepActions
        onContinue={connect}
        onBack={onBack}
        onSkip={onSkip}
        continueLabel={existing ? 'Continuar' : 'Conectar Shopify'}
        continueLoading={connectMutation.isPending}
      />
    </WizardSplitLayout>
  )
}
