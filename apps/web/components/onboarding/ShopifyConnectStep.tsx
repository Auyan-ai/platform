'use client'

import { useState } from 'react'
import { CheckCircle2, Plug } from 'lucide-react'
import {
  useConnectShopify,
  useTenantIntegrations,
  type TenantIntegrationStatus,
} from '@/lib/api/hooks/tenant-context'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

function findShopify(
  integrations: TenantIntegrationStatus[] | undefined,
): TenantIntegrationStatus | undefined {
  return integrations?.find((i) => i.kind === 'commerce' && i.provider === 'shopify' && i.is_active)
}

export function ShopifyConnectStep({ tenantId }: { tenantId: string }) {
  const integrationsQuery = useTenantIntegrations(tenantId)
  const connectMutation = useConnectShopify(tenantId)
  const existing = findShopify(integrationsQuery.data?.integrations)

  const [domain, setDomain] = useState('')
  const [clientId, setClientId] = useState('')
  const [clientSecret, setClientSecret] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    setError(null)
    if (!domain.trim() || !clientId.trim() || !clientSecret.trim()) {
      setError('Dominio, Client ID y Client Secret son obligatorios.')
      return
    }
    try {
      await connectMutation.mutateAsync({
        domain: domain.trim(),
        client_id: clientId.trim(),
        client_secret: clientSecret.trim(),
      })
      setClientSecret('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo conectar Shopify.')
    }
  }

  return (
    <div className="grid gap-5">
      <p className="text-sm text-foreground-muted">
        Conecta la API de administración de tu tienda Shopify. Desde el 1 de enero 2026
        las apps se crean en el{' '}
        <a
          href="https://shopify.dev/dashboard"
          target="_blank"
          rel="noopener noreferrer"
          className="text-accent underline"
        >
          Shopify Dev Dashboard
        </a>{' '}
        y usan Client ID + Client Secret (OAuth Client Credentials, token rotación
        automática cada 24h).
      </p>

      {existing && (
        <div className="flex items-start gap-2 rounded-md border border-success bg-success-subtle px-3 py-2 text-sm text-success-foreground">
          <CheckCircle2 className="size-4 shrink-0" />
          <div>
            <p className="font-medium">Shopify conectado</p>
            <p className="text-xs opacity-80">
              Dominio: {String(existing.config.domain ?? '—')}. Puedes reemplazar el secret
              re-enviando el formulario.
            </p>
          </div>
        </div>
      )}

      <div className="grid gap-3">
        <div>
          <Label htmlFor="shopify-domain">Dominio Shopify</Label>
          <Input
            id="shopify-domain"
            value={domain}
            placeholder="mareastudio.myshopify.com"
            onChange={(e) => setDomain(e.target.value)}
            className="mt-1.5"
          />
        </div>
        <div>
          <Label htmlFor="shopify-client-id">Client ID</Label>
          <Input
            id="shopify-client-id"
            value={clientId}
            placeholder="abc123..."
            onChange={(e) => setClientId(e.target.value)}
            className="mt-1.5"
          />
        </div>
        <div>
          <Label htmlFor="shopify-client-secret">Client Secret</Label>
          <Input
            id="shopify-client-secret"
            type="password"
            value={clientSecret}
            placeholder="shpss_..."
            onChange={(e) => setClientSecret(e.target.value)}
            className="mt-1.5"
          />
          <p className="mt-1 text-xs text-foreground-muted">
            Lo guardamos cifrado. Nunca lo verás en el panel después de enviarlo.
          </p>
        </div>
      </div>

      {error && (
        <p className="text-sm text-danger-foreground">{error}</p>
      )}

      <div>
        <Button onClick={submit} disabled={connectMutation.isPending}>
          <Plug className="size-4" />
          {connectMutation.isPending ? 'Conectando...' : existing ? 'Reemplazar secret' : 'Conectar Shopify'}
        </Button>
      </div>
    </div>
  )
}
