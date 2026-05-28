import { redirect } from 'next/navigation'

interface Props {
  params: Promise<{ tenantId: string; id: string }>
}

export default async function ClientConversationDetailPage({ params }: Props) {
  const { tenantId, id } = await params

  redirect(`/clients/${tenantId}/insights/${id}`)
}
