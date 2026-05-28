import { ApprovalQueue } from '@/components/inbox/ApprovalQueue'

interface Props {
  params: Promise<{ tenantId: string }>
}

export default async function ClientApprovalsPage({ params }: Props) {
  const { tenantId } = await params

  return (
    <ApprovalQueue tenantId={tenantId} conversationBasePath={`/clients/${tenantId}/insights`} />
  )
}
