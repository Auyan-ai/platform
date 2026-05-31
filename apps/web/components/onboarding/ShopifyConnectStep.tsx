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
  const [token, setToken] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    setError(null)
    if (!domain.trim() || !token.trim()) {
      setError('Dominio y token son obligatorios.')
      return
    }
    try {
      await connectMutation.mutateAsync({ domain: domain.trim(), token: token.trim() })
      setToken('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo conectar Shopify.')
    }
  }

  return (
    <div className="grid gap-5">
      <p className="text-sm text-foreground-muted">
        Conecta la API de administración de tu tienda Shopify. Necesitas un{' '}
        <a
          href="https://help.shopify.com/en/manual/apps/app-types/custom-apps"
          target="_blank"
          rel="noopener noreferrer"
          className="text-accent underline"
        >
          Custom App
        </a>{' '}
        con scopes de lectura para orders, products, customers y policies.
      </p>

      {existing && (
        <div className="flex items-start gap-2 rounded-md border border-success bg-success-subtle px-3 py-2 text-sm text-success-foreground">
          <CheckCircle2 className="size-4 shrink-0" />
          <div>
            <p className="font-medium">Shopify conectado</p>
            <p className="text-xs opacity-80">
              Dominio: {String(existing.config.domain ?? '—')}. Puedes reemplazar el token
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
          <Label htmlFor="shopify-token">Admin API access token</Label>
          <Input
            id="shopify-token"
            type="password"
            value={token}
            placeholder="shpat_..."
            onChange={(e) => setToken(e.target.value)}
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
          {connectMutation.isPending ? 'Conectando...' : existing ? 'Reemplazar token' : 'Conectar Shopify'}
        </Button>
      </div>
    </div>
  )
}
