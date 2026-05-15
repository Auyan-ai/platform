import { EscalationQueue } from '@/components/inbox/EscalationQueue'

export default async function EscalationsPage({
  params,
}: {
  params: Promise<{ tenantId: string }>
}) {
  const { tenantId } = await params
  return <EscalationQueue tenantId={tenantId} />
}
