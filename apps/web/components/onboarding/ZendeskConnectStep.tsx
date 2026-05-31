'use client'

import { useState } from 'react'
import { CheckCircle2, ExternalLink } from 'lucide-react'
import {
  fetchOAuthAuthorizeUrl,
  useTenantIntegrations,
  type TenantIntegrationStatus,
} from '@/lib/api/hooks/tenant-context'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

function findZendesk(
  integrations: TenantIntegrationStatus[] | undefined,
): TenantIntegrationStatus | undefined {
  return integrations?.find((i) => i.kind === 'helpdesk' && i.provider === 'zendesk' && i.is_active)
}

export function ZendeskConnectStep({ tenantId }: { tenantId: string }) {
  const integrationsQuery = useTenantIntegrations(tenantId)
  const existing = findZendesk(integrationsQuery.data?.integrations)

  const [subdomain, setSubdomain] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function connect() {
    setError(null)
    if (!subdomain.trim()) {
      setError('Falta el subdominio de Zendesk.')
      return
    }
    setBusy(true)
    try {
      const url = await fetchOAuthAuthorizeUrl('zendesk', {
        tenant_id: tenantId,
        subdomain: subdomain.trim(),
      })
      window.location.href = url
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo iniciar OAuth.')
      setBusy(false)
    }
  }

  return (
    <div className="grid gap-5">
      <p className="text-sm text-foreground-muted">
        Conecta tu cuenta Zendesk con OAuth. Te llevaremos a Zendesk para autorizar y
        volveremos al wizard automáticamente.
      </p>

      {existing && (
        <div className="flex items-start gap-2 rounded-md border border-success bg-success-subtle px-3 py-2 text-sm text-success-foreground">
          <CheckCircle2 className="size-4 shrink-0" />
          <div>
            <p className="font-medium">Zendesk conectado</p>
            <p className="text-xs opacity-80">
              Subdominio: {String(existing.config.subdomain ?? '—')}
            </p>
          </div>
        </div>
      )}

      <div>
        <Label htmlFor="zd-subdomain">Subdominio Zendesk</Label>
        <Input
          id="zd-subdomain"
          value={subdomain}
          placeholder="mitienda"
          onChange={(e) => setSubdomain(e.target.value)}
          className="mt-1.5"
        />
        <p className="mt-1 text-xs text-foreground-muted">
          Si tu URL es <code>mitienda.zendesk.com</code>, el subdominio es{' '}
          <code>mitienda</code>.
        </p>
      </div>

      {error && <p className="text-sm text-danger-foreground">{error}</p>}

      <div>
        <Button onClick={connect} disabled={busy}>
          <ExternalLink className="size-4" />
          {busy ? 'Redirigiendo...' : existing ? 'Reconectar Zendesk' : 'Conectar con Zendesk'}
        </Button>
      </div>
    </div>
  )
}
