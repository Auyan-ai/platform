import { ConversationList } from '@/components/inbox/ConversationList'

interface Props {
  params: Promise<{ tenantId: string }>
}

export default async function ClientConversationsPage({ params }: Props) {
  const { tenantId } = await params
  return (
    <ConversationList
      tenantId={tenantId}
      basePath={`/clients/${tenantId}/conversations`}
    />
  )
}
