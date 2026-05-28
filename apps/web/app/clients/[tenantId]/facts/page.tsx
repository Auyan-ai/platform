import { redirect } from 'next/navigation'

interface Props {
  params: Promise<{ tenantId: string }>
}

export default async function ClientFactsPage({ params }: Props) {
  const { tenantId } = await params

  redirect(`/clients/${tenantId}/knowledge`)
}
