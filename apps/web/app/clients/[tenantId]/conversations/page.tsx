import { redirect } from 'next/navigation'

interface Props {
  params: Promise<{ tenantId: string }>
}

export default async function ClientConversationsPage({ params }: Props) {
  const { tenantId } = await params

  redirect(`/clients/${tenantId}/insights`)
}
