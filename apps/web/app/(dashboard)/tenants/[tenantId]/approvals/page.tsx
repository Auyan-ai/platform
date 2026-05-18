import { ApprovalQueue } from '@/components/inbox/ApprovalQueue'

export default async function ApprovalsPage({
  params,
}: {
  params: Promise<{ tenantId: string }>
}) {
  const { tenantId } = await params
  return <ApprovalQueue tenantId={tenantId} />
}
