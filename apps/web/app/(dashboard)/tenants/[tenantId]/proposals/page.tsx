import { ProposalQueue } from '@/components/proposals/ProposalQueue'
import { ProposalMetrics } from '@/components/proposals/ProposalMetrics'

export default async function ProposalsPage({
  params,
}: {
  params: Promise<{ tenantId: string }>
}) {
  const { tenantId } = await params

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-neutral-900">Mejoras propuestas</h1>
        <p className="text-sm text-neutral-500 mt-0.5">
          Propuestas generadas automáticamente por el slow agent tras analizar conversaciones
        </p>
      </div>

      <ProposalMetrics tenantId={tenantId} />

      <ProposalQueue tenantId={tenantId} />
    </div>
  )
}
