import { OutboundEmailConsole } from '@/components/email/OutboundEmailConsole'

interface Props {
  params: Promise<{ tenantId: string }>
}

export default async function TenantEmailsPage({ params }: Props) {
  const { tenantId } = await params

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-medium uppercase tracking-wider text-foreground-muted">
          Outbound email
        </p>
        <h1 className="mt-1 text-2xl font-semibold text-foreground">Emails operativos</h1>
        <p className="mt-1 max-w-2xl text-sm text-foreground-muted">
          Gestiona templates, encola envíos y revisa estado reciente de entrega por tenant.
        </p>
      </div>

      <OutboundEmailConsole tenantId={tenantId} />
    </div>
  )
}
