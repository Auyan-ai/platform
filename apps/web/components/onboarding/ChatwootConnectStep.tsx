'use client'

import { useState } from 'react'
import { CheckCircle2, Plug } from 'lucide-react'
import {
  useConnectChatwoot,
  useTenantIntegrations,
  type TenantIntegrationStatus,
} from '@/lib/api/hooks/tenant-context'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

function findChatwoot(
  integrations: TenantIntegrationStatus[] | undefined,
): TenantIntegrationStatus | undefined {
  return integrations?.find((i) => i.kind === 'helpdesk' && i.provider === 'chatwoot' && i.is_active)
}

export function ChatwootConnectStep({ tenantId }: { tenantId: string }) {
  const integrationsQuery = useTenantIntegrations(tenantId)
  const connectMutation = useConnectChatwoot(tenantId)
  const existing = findChatwoot(integrationsQuery.data?.integrations)

  const [baseUrl, setBaseUrl] = useState('https://app.chatwoot.com')
  const [accountId, setAccountId] = useState('')
  const [apiToken, setApiToken] = useState('')
  const [escalationTeam, setEscalationTeam] = useState('')
  const [result, setResult] = useState<{ webhook_registered: boolean | null } | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    setError(null)
    setResult(null)
    if (!baseUrl.trim() || !accountId.trim() || !apiToken.trim()) {
      setError('Base URL, account ID y access token son obligatorios.')
      return
    }
    try {
      const resp = await connectMutation.mutateAsync({
        base_url: baseUrl.trim(),
        account_id: accountId.trim(),
        api_access_token: apiToken.trim(),
        escalation_team_id: escalationTeam.trim() || null,
      })
      setApiToken('')
      setResult({ webhook_registered: resp.webhook_registered })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo conectar Chatwoot.')
    }
  }

  return (
    <div className="grid gap-5">
      <p className="text-sm text-foreground-muted">
        Necesitamos una{' '}
        <a
          href="https://www.chatwoot.com/docs/product/account/api"
          target="_blank"
          rel="noopener noreferrer"
          className="text-accent underline"
        >
          API access token
        </a>{' '}
        con permisos sobre la cuenta. Auyan registra automáticamente el webhook entrante
        si tenemos configurada la URL pública de la API.
      </p>

      {existing && (
        <div className="flex items-start gap-2 rounded-md border border-success bg-success-subtle px-3 py-2 text-sm text-success-foreground">
          <CheckCircle2 className="size-4 shrink-0" />
          <div>
            <p className="font-medium">Chatwoot conectado</p>
            <p className="text-xs opacity-80">
              {String(existing.config.base_url ?? '—')} · account_id{' '}
              {String(existing.config.account_id ?? '—')}
              {existing.config.webhook_registered ? ' · webhook activo' : ''}
            </p>
          </div>
        </div>
      )}

      <div className="grid gap-3">
        <div>
          <Label htmlFor="cw-base">Base URL</Label>
          <Input
            id="cw-base"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            className="mt-1.5"
          />
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <Label htmlFor="cw-account">Account ID</Label>
            <Input
              id="cw-account"
              value={accountId}
              placeholder="1"
              onChange={(e) => setAccountId(e.target.value)}
              className="mt-1.5"
            />
          </div>
          <div>
            <Label htmlFor="cw-team">Equipo de escalación (opcional)</Label>
            <Input
              id="cw-team"
              value={escalationTeam}
              placeholder="ID del team"
              onChange={(e) => setEscalationTeam(e.target.value)}
              className="mt-1.5"
            />
          </div>
        </div>
        <div>
          <Label htmlFor="cw-token">API access token</Label>
          <Input
            id="cw-token"
            type="password"
            value={apiToken}
            onChange={(e) => setApiToken(e.target.value)}
            className="mt-1.5"
          />
          <p className="mt-1 text-xs text-foreground-muted">
            Se guarda cifrado. No lo verás en el panel después de enviarlo.
          </p>
        </div>
      </div>

      {error && <p className="text-sm text-danger-foreground">{error}</p>}
      {result && (
        <p className="text-sm text-foreground-muted">
          {result.webhook_registered === true
            ? 'Webhook entrante registrado en Chatwoot.'
            : result.webhook_registered === false
              ? 'No se pudo registrar el webhook entrante (revisa los logs o configúralo manualmente).'
              : 'Conexión guardada. Tu API base URL no está configurada — el webhook hay que registrarlo a mano.'}
        </p>
      )}

      <div>
        <Button onClick={submit} disabled={connectMutation.isPending}>
          <Plug className="size-4" />
          {connectMutation.isPending ? 'Conectando...' : existing ? 'Reemplazar token' : 'Conectar Chatwoot'}
        </Button>
      </div>
    </div>
  )
}
