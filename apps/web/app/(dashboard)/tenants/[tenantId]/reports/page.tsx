import { WeeklyReportConsole } from '@/components/reports/WeeklyReportConsole'

interface Props {
  params: Promise<{ tenantId: string }>
}

export default async function TenantReportsPage({ params }: Props) {
  const { tenantId } = await params

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-medium uppercase tracking-wider text-foreground-muted">
          Weekly reporting
        </p>
        <h1 className="mt-1 text-2xl font-semibold text-foreground">Reportes semanales</h1>
        <p className="mt-1 max-w-2xl text-sm text-foreground-muted">
          Genera, edita, aprueba y envía reportes semanales por tenant.
        </p>
      </div>

      <WeeklyReportConsole tenantId={tenantId} />
    </div>
  )
}
