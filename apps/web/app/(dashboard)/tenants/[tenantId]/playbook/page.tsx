import { TenantPlaybookEditor } from '@/components/tenant-context/TenantPlaybookEditor'

interface Props {
  params: Promise<{ tenantId: string }>
}

export default async function TenantPlaybookPage({ params }: Props) {
  const { tenantId } = await params

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-foreground-muted">
            Knowledge ops
          </p>
          <h1 className="mt-1 text-2xl font-semibold text-foreground">Playbook del cliente</h1>
          <p className="mt-1 max-w-2xl text-sm text-foreground-muted">
            La biblia operativa que Auyan mantiene para que el agente responda como el cliente.
          </p>
        </div>
      </div>

      <TenantPlaybookEditor tenantId={tenantId} />
    </div>
  )
}
