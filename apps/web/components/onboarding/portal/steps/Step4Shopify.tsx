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

      <div className="mt-7 grid gap-2">
        <WizardInput
          placeholder="mareastudio.myshopify.com"
          value={domain}
          onChange={(e) => setDomain(e.target.value)}
        />
        <WizardInput
          type="password"
          placeholder="Admin API access token (shpat_...)"
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
