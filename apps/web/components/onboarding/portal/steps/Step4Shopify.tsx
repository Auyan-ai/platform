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

export function Step4Shopify({ tenantId, onContinue, onSkip }: StepProps) {
  const integrationsQuery = useTenantIntegrations(tenantId)
  const connectMutation = useConnectShopify(tenantId)
  const existing = findShopify(integrationsQuery.data?.integrations)

  const [domain, setDomain] = useState('')
  const [token, setToken] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function connect() {
    setError(null)
    if (!domain.trim() || !token.trim()) {
      setError('Dominio y token son obligatorios.')
      return
    }
    try {
      await connectMutation.mutateAsync({ domain: domain.trim(), token: token.trim() })
      setToken('')
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
          ¿De dónde saco el Admin API access token?
        </summary>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-foreground-muted">
          <li>
            En tu Shopify Admin: <strong>Settings → Apps and sales channels → Develop apps</strong>.
          </li>
          <li>
            Haz click en <strong>Create an app</strong> (o selecciona una existente). Nombre:{' '}
            <code className="rounded-xs bg-surface px-1 py-0.5">Auyan</code>.
          </li>
          <li>
            Pestaña <strong>Configuration → Admin API access scopes</strong>. Activa:{' '}
            <code className="rounded-xs bg-surface px-1 py-0.5">read_orders</code>,{' '}
            <code className="rounded-xs bg-surface px-1 py-0.5">read_products</code>,{' '}
            <code className="rounded-xs bg-surface px-1 py-0.5">read_customers</code>,{' '}
            <code className="rounded-xs bg-surface px-1 py-0.5">read_content</code>.
          </li>
          <li>
            Pestaña <strong>API credentials → Install app</strong>. Aparece el{' '}
            <strong>Admin API access token</strong> que empieza con{' '}
            <code className="rounded-xs bg-surface px-1 py-0.5">shpat_</code>. Cópialo{' '}
            <strong>una sola vez</strong> y pégalo abajo.
          </li>
        </ol>
        <a
          href="https://help.shopify.com/en/manual/apps/app-types/custom-apps"
          target="_blank"
          rel="noopener noreferrer"
          className="mt-2 inline-block text-accent hover:underline"
        >
          Documentación oficial de Shopify ↗
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
          label="Admin API access token"
          type="password"
          placeholder="shpat_..."
          value={token}
          onChange={(e) => setToken(e.target.value)}
        />
      </div>

      {error && <p className="mt-3 text-sm text-danger-foreground">{error}</p>}

      <WizardStepActions
        onContinue={connect}
        onSkip={onSkip}
        continueLabel={existing ? 'Continuar' : 'Conectar Shopify'}
        continueLoading={connectMutation.isPending}
      />
    </WizardSplitLayout>
  )
}
