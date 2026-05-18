import Link from 'next/link'
import { ProposalDetail } from '@/components/proposals/ProposalDetail'

export default async function ProposalDetailPage({
  params,
}: {
  params: Promise<{ tenantId: string; proposalId: string }>
}) {
  const { tenantId, proposalId } = await params

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2 text-sm text-neutral-500">
        <Link
          href={`/tenants/${tenantId}/proposals`}
          className="hover:text-neutral-900 transition-colors"
        >
          Mejoras propuestas
        </Link>
        <span>/</span>
        <span className="text-neutral-700 font-mono text-xs truncate max-w-xs">
          {proposalId}
        </span>
      </div>

      <ProposalDetail tenantId={tenantId} proposalId={proposalId} />
    </div>
  )
}
