import { ConversationDetail } from '@/components/inbox/ConversationDetail'

interface Props {
  params: Promise<{ tenantId: string; id: string }>
}

export default async function ClientInsightDetailPage({ params }: Props) {
  const { tenantId, id } = await params

  return (
    <ConversationDetail
      tenantId={tenantId}
      conversationId={id}
      readOnly
      maskPII
      backHref={`/clients/${tenantId}/insights`}
    />
  )
}
