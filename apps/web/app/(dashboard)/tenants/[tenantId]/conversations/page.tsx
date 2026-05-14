import { ConversationList } from '@/components/inbox/ConversationList'

export default async function ConversationsPage({
  params,
}: {
  params: Promise<{ tenantId: string }>
}) {
  const { tenantId } = await params
  return <ConversationList tenantId={tenantId} />
}
