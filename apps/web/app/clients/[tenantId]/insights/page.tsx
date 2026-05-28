import { ConversationList } from '@/components/inbox/ConversationList'

interface Props {
  params: Promise<{ tenantId: string }>
}

export default async function ClientInsightsPage({ params }: Props) {
  const { tenantId } = await params

  return (
    <ConversationList
      tenantId={tenantId}
      basePath={`/clients/${tenantId}/insights`}
      title="Insights"
      description="Explorer de conversaciones, estados y canales con drill-down al razonamiento del agente."
    />
  )
}
