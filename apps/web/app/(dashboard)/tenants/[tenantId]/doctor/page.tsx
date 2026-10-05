import { TenantDoctorPanel } from '@/components/doctor/TenantDoctorPanel'

interface Props {
  params: Promise<{ tenantId: string }>
}

export default async function TenantDoctorPage({ params }: Props) {
  const { tenantId } = await params

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-medium uppercase tracking-wider text-foreground-muted">
          Operación
        </p>
        <h1 className="mt-1 text-2xl font-semibold text-foreground">Diagnóstico</h1>
        <p className="mt-1 max-w-2xl text-sm text-foreground-muted">
          Comprueba en vivo lo que el tenant necesita para funcionar: migraciones, helpdesk,
          triggers y webhooks, WhatsApp y la cola de turnos. Solo lee; no cambia nada.
        </p>
      </div>

      <TenantDoctorPanel tenantId={tenantId} />
    </div>
  )
}
