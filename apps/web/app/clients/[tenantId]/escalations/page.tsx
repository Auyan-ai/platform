import { EscalationQueue } from '@/components/inbox/EscalationQueue'

interface Props {
  params: Promise<{ tenantId: string }>
}

export default async function ClientEscalationsPage({ params }: Props) {
  const { tenantId } = await params
  return (
    <EscalationQueue
      tenantId={tenantId}
      readOnly
      conversationBasePath={`/clients/${tenantId}/insights`}
    />
  )
}
