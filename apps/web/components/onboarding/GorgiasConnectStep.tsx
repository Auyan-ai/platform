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

function findGorgias(
  integrations: TenantIntegrationStatus[] | undefined,
): TenantIntegrationStatus | undefined {
  return integrations?.find((i) => i.kind === 'helpdesk' && i.provider === 'gorgias' && i.is_active)
}

export function GorgiasConnectStep({ tenantId }: { tenantId: string }) {
  const integrationsQuery = useTenantIntegrations(tenantId)
  const existing = findGorgias(integrationsQuery.data?.integrations)

  const [domain, setDomain] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function connect() {
    setError(null)
    if (!domain.trim()) {
      setError('Falta el subdominio de Gorgias.')
      return
    }
    setBusy(true)
    try {
      const url = await fetchOAuthAuthorizeUrl('gorgias', {
        tenant_id: tenantId,
        domain: domain.trim(),
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
        Conecta tu cuenta Gorgias con OAuth. Te llevaremos a Gorgias para autorizar y
        volveremos al wizard automáticamente.
      </p>

      {existing && (
        <div className="flex items-start gap-2 rounded-md border border-success bg-success-subtle px-3 py-2 text-sm text-success-foreground">
          <CheckCircle2 className="size-4 shrink-0" />
          <div>
            <p className="font-medium">Gorgias conectado</p>
            <p className="text-xs opacity-80">
              Dominio: {String(existing.config.domain ?? '—')}
            </p>
          </div>
        </div>
      )}

      <div>
        <Label htmlFor="gorgias-domain">Subdominio Gorgias</Label>
        <Input
          id="gorgias-domain"
          value={domain}
          placeholder="mitienda"
          onChange={(e) => setDomain(e.target.value)}
          className="mt-1.5"
        />
        <p className="mt-1 text-xs text-foreground-muted">
          Si tu URL es <code>mitienda.gorgias.com</code>, el subdominio es{' '}
          <code>mitienda</code>.
        </p>
      </div>

      {error && <p className="text-sm text-danger-foreground">{error}</p>}

      <div>
        <Button onClick={connect} disabled={busy}>
          <ExternalLink className="size-4" />
          {busy ? 'Redirigiendo...' : existing ? 'Reconectar Gorgias' : 'Conectar con Gorgias'}
        </Button>
      </div>
    </div>
  )
}
