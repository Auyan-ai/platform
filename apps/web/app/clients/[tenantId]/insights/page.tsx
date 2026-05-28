import { ClientInsightsExplorer } from '@/components/clients/ClientInsightsExplorer'

interface Props {
  params: Promise<{ tenantId: string }>
}

export default async function ClientInsightsPage({ params }: Props) {
  const { tenantId } = await params

  return <ClientInsightsExplorer tenantId={tenantId} />
}
