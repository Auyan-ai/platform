'use client'

import { useState } from 'react'
import { CheckCircle2, Plug } from 'lucide-react'
import {
  useConnectWooCommerce,
  useTenantIntegrations,
  type TenantIntegrationStatus,
} from '@/lib/api/hooks/tenant-context'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

function findWooCommerce(
  integrations: TenantIntegrationStatus[] | undefined,
): TenantIntegrationStatus | undefined {
  return integrations?.find(
    (i) => i.kind === 'commerce' && i.provider === 'woocommerce' && i.is_active,
  )
}

export function WooCommerceConnectStep({ tenantId }: { tenantId: string }) {
  const integrationsQuery = useTenantIntegrations(tenantId)
  const connectMutation = useConnectWooCommerce(tenantId)
  const existing = findWooCommerce(integrationsQuery.data?.integrations)

  const [storeUrl, setStoreUrl] = useState('')
  const [consumerKey, setConsumerKey] = useState('')
  const [consumerSecret, setConsumerSecret] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    setError(null)
    if (!storeUrl.trim() || !consumerKey.trim() || !consumerSecret.trim()) {
      setError('URL de la tienda, consumer key y consumer secret son obligatorios.')
      return
    }
    try {
      await connectMutation.mutateAsync({
        store_url: storeUrl.trim(),
        consumer_key: consumerKey.trim(),
        consumer_secret: consumerSecret.trim(),
      })
      setConsumerSecret('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo conectar WooCommerce.')
    }
  }

  return (
    <div className="grid gap-5">
      <p className="text-sm text-foreground-muted">
        En WordPress, ve a WooCommerce → Ajustes → Avanzado → REST API y crea una clave con
        permisos de Lectura/Escritura. La tienda tiene que servirse por https.
      </p>

      {existing && (
        <div className="flex items-start gap-2 rounded-md border border-success bg-success-subtle px-3 py-2 text-sm text-success-foreground">
          <CheckCircle2 className="size-4 shrink-0" />
          <div>
            <p className="font-medium">WooCommerce conectado</p>
            <p className="text-xs opacity-80">
              Tienda: {String(existing.config.store_url ?? '—')}. Puedes reemplazar las claves
              re-enviando el formulario.
            </p>
          </div>
        </div>
      )}

      <div className="grid gap-3">
        <div>
          <Label htmlFor="woocommerce-store-url">URL de la tienda</Label>
          <Input
            id="woocommerce-store-url"
            value={storeUrl}
            placeholder="https://tienda.es"
            onChange={(e) => setStoreUrl(e.target.value)}
            className="mt-1.5"
          />
        </div>
        <div>
          <Label htmlFor="woocommerce-consumer-key">Consumer key</Label>
          <Input
            id="woocommerce-consumer-key"
            value={consumerKey}
            placeholder="ck_..."
            onChange={(e) => setConsumerKey(e.target.value)}
            className="mt-1.5"
          />
        </div>
        <div>
          <Label htmlFor="woocommerce-consumer-secret">Consumer secret</Label>
          <Input
            id="woocommerce-consumer-secret"
            type="password"
            value={consumerSecret}
            placeholder="cs_..."
            onChange={(e) => setConsumerSecret(e.target.value)}
            className="mt-1.5"
          />
          <p className="mt-1 text-xs text-foreground-muted">
            Lo guardamos cifrado. Nunca lo verás en el panel después de enviarlo.
          </p>
        </div>
      </div>

      {error && <p className="text-sm text-danger-foreground">{error}</p>}

      <div>
        <Button onClick={submit} disabled={connectMutation.isPending}>
          <Plug className="size-4" />
          {connectMutation.isPending
            ? 'Conectando...'
            : existing
              ? 'Reemplazar claves'
              : 'Conectar WooCommerce'}
        </Button>
      </div>
    </div>
  )
}
