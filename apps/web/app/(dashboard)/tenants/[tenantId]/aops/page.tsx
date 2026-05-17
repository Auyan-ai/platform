import { AopList } from '@/components/aops/AopList'

export default async function AopsPage({
  params,
}: {
  params: Promise<{ tenantId: string }>
}) {
  const { tenantId } = await params
  return <AopList tenantId={tenantId} />
}
