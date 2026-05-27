import { TenantFactsForm } from '@/components/tenant-context/TenantFactsForm'

interface Props {
  params: Promise<{ tenantId: string }>
}

export default async function ClientFactsPage({ params }: Props) {
  const { tenantId } = await params

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-medium uppercase tracking-wider text-foreground-muted">
          Contexto del agente
        </p>
        <h1 className="mt-1 text-2xl font-semibold text-foreground">Datos de tu cuenta</h1>
        <p className="mt-1 max-w-2xl text-sm text-foreground-muted">
          Información factual que el agente usa para responder sin esperar curación de Auyan.
        </p>
      </div>

      <TenantFactsForm tenantId={tenantId} />
    </div>
  )
}
