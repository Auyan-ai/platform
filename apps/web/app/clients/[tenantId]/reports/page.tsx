import { WeeklyReportHistory } from '@/components/reports/WeeklyReportHistory'

interface Props {
  params: Promise<{ tenantId: string }>
}

export default async function ClientReportsPage({ params }: Props) {
  const { tenantId } = await params

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-medium uppercase tracking-wider text-foreground-muted">
          Reportes semanales
        </p>
        <h1 className="mt-1 text-2xl font-semibold text-foreground">Reportes</h1>
        <p className="mt-1 max-w-2xl text-sm text-foreground-muted">
          Historial de reportes enviados por Auyan sobre la operación de tu agente.
        </p>
      </div>

      <WeeklyReportHistory tenantId={tenantId} />
    </div>
  )
}
