'use client'

import { useState } from 'react'
import { CheckCircle2, ExternalLink } from 'lucide-react'
import { WizardSplitLayout } from '../WizardLayouts'
import { WizardInput } from '../WizardInput'
import { WizardStepHeader } from '../WizardStepHeader'
import { WizardStepActions } from '../WizardStepActions'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import {
  fetchOAuthAuthorizeUrl,
  useConnectChatwoot,
  useTenantIntegrations,
  type TenantIntegrationStatus,
} from '@/lib/api/hooks/tenant-context'
import type { StepProps } from './types'

function findHelpdesk(
  integrations: TenantIntegrationStatus[] | undefined,
  provider: string,
): TenantIntegrationStatus | undefined {
  return integrations?.find((i) => i.kind === 'helpdesk' && i.provider === provider && i.is_active)
}

function ChatwootPane({ tenantId, onContinue }: { tenantId: string; onContinue: () => void }) {
  const integrationsQuery = useTenantIntegrations(tenantId)
  const connectMutation = useConnectChatwoot(tenantId)
  const existing = findHelpdesk(integrationsQuery.data?.integrations, 'chatwoot')

  const [baseUrl, setBaseUrl] = useState('https://app.chatwoot.com')
  const [accountId, setAccountId] = useState('')
  const [apiToken, setApiToken] = useState('')
  const [escalationTeam, setEscalationTeam] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function connect() {
    setError(null)
    if (!baseUrl.trim() || !accountId.trim() || !apiToken.trim()) {
      setError('Base URL, account ID y access token son obligatorios.')
      return
    }
    try {
      await connectMutation.mutateAsync({
        base_url: baseUrl.trim(),
        account_id: accountId.trim(),
        api_access_token: apiToken.trim(),
        escalation_team_id: escalationTeam.trim() || null,
      })
      setApiToken('')
      onContinue()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo conectar Chatwoot.')
    }
  }

  return (
    <div>
      {existing && (
        <div className="mb-4 flex items-start gap-2 rounded-md border border-success bg-success-subtle px-3 py-2 text-sm text-success-foreground">
          <CheckCircle2 className="size-4 shrink-0" />
          <div>
            <p className="font-medium">Chatwoot conectado</p>
            <p className="text-xs opacity-80">
              {String(existing.config.base_url ?? '—')} · account{' '}
              {String(existing.config.account_id ?? '—')}
            </p>
          </div>
        </div>
      )}
      <div className="grid gap-2">
        <WizardInput placeholder="Base URL" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
        <div className="grid grid-cols-2 gap-2">
          <WizardInput placeholder="Account ID" value={accountId} onChange={(e) => setAccountId(e.target.value)} />
          <WizardInput
            placeholder="Equipo escalación (opcional)"
            value={escalationTeam}
            onChange={(e) => setEscalationTeam(e.target.value)}
          />
        </div>
        <WizardInput
          type="password"
          placeholder="API access token"
          value={apiToken}
          onChange={(e) => setApiToken(e.target.value)}
        />
      </div>
      {error && <p className="mt-3 text-sm text-danger-foreground">{error}</p>}
      <div className="mt-4 flex justify-end">
        <Button onClick={connect} disabled={connectMutation.isPending}>
          {connectMutation.isPending ? 'Conectando...' : existing ? 'Continuar' : 'Conectar Chatwoot'}
        </Button>
      </div>
    </div>
  )
}

function OAuthPane({
  tenantId,
  provider,
  onContinue,
  inputLabel,
  inputPlaceholder,
  paramKey,
  hint,
}: {
  tenantId: string
  provider: 'gorgias' | 'zendesk'
  onContinue: () => void
  inputLabel: string
  inputPlaceholder: string
  paramKey: 'domain' | 'subdomain'
  hint: string
}) {
  const integrationsQuery = useTenantIntegrations(tenantId)
  const existing = findHelpdesk(integrationsQuery.data?.integrations, provider)
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function connect() {
    setError(null)
    if (!value.trim()) {
      setError(`Falta el ${inputLabel.toLowerCase()}.`)
      return
    }
    if (existing) {
      onContinue()
      return
    }
    setBusy(true)
    try {
      const url = await fetchOAuthAuthorizeUrl(provider, {
        tenant_id: tenantId,
        [paramKey]: value.trim(),
      })
      window.location.href = url
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo iniciar OAuth.')
      setBusy(false)
    }
  }

  return (
    <div>
      {existing && (
        <div className="mb-4 flex items-start gap-2 rounded-md border border-success bg-success-subtle px-3 py-2 text-sm text-success-foreground">
          <CheckCircle2 className="size-4 shrink-0" />
          <div>
            <p className="font-medium capitalize">{provider} conectado</p>
          </div>
        </div>
      )}
      <WizardInput
        label={inputLabel}
        placeholder={inputPlaceholder}
        value={value}
        onChange={(e) => setValue(e.target.value)}
      />
      <p className="mt-1.5 text-xs text-foreground-muted">{hint}</p>
      {error && <p className="mt-3 text-sm text-danger-foreground">{error}</p>}
      <div className="mt-4 flex justify-end">
        <Button onClick={connect} disabled={busy}>
          <ExternalLink className="size-4" />
          {busy ? 'Redirigiendo...' : existing ? 'Continuar' : `Conectar ${provider}`}
        </Button>
      </div>
    </div>
  )
}

export function Step5Helpdesk({ tenantId, onContinue, onSkip }: StepProps) {
  return (
    <WizardSplitLayout>
      <WizardStepHeader
        title="Conecta tu helpdesk"
        subtitle="Donde llegan los tickets. Chatwoot usa API token; Gorgias y Zendesk OAuth de un click."
      />

      <Tabs defaultValue="chatwoot">
        <TabsList>
          <TabsTrigger value="chatwoot">Chatwoot</TabsTrigger>
          <TabsTrigger value="gorgias">Gorgias</TabsTrigger>
          <TabsTrigger value="zendesk">Zendesk</TabsTrigger>
        </TabsList>

        <TabsContent value="chatwoot">
          <ChatwootPane tenantId={tenantId} onContinue={onContinue} />
        </TabsContent>
        <TabsContent value="gorgias">
          <OAuthPane
            tenantId={tenantId}
            provider="gorgias"
            onContinue={onContinue}
            inputLabel="Subdominio Gorgias"
            inputPlaceholder="mitienda"
            paramKey="domain"
            hint="Si tu URL es mitienda.gorgias.com, el subdominio es mitienda."
          />
        </TabsContent>
        <TabsContent value="zendesk">
          <OAuthPane
            tenantId={tenantId}
            provider="zendesk"
            onContinue={onContinue}
            inputLabel="Subdominio Zendesk"
            inputPlaceholder="mitienda"
            paramKey="subdomain"
            hint="Si tu URL es mitienda.zendesk.com, el subdominio es mitienda."
          />
        </TabsContent>
      </Tabs>

      {onSkip && (
        <div className="mt-4 flex justify-end">
          <button
            type="button"
            onClick={onSkip}
            className="rounded-sm px-2 py-1.5 text-xs text-foreground-muted transition-colors hover:bg-surface-muted hover:text-foreground-body"
          >
            Skip por ahora
          </button>
        </div>
      )}
    </WizardSplitLayout>
  )
}
