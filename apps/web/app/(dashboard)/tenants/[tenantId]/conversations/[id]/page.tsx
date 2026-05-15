import { ConversationDetail } from '@/components/inbox/ConversationDetail'

export default async function ConversationDetailPage({
  params,
}: {
  params: Promise<{ tenantId: string; id: string }>
}) {
  const { tenantId, id } = await params
  return <ConversationDetail tenantId={tenantId} conversationId={id} />
}
