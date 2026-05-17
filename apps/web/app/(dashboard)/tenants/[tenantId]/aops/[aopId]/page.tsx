import Link from 'next/link'
import { AopEditView } from '@/components/aops/AopEditView'

export default async function EditAopPage({
  params,
}: {
  params: Promise<{ tenantId: string; aopId: string }>
}) {
  const { tenantId, aopId } = await params
  return (
    <div className="max-w-5xl mx-auto">
      <div className="mb-4">
        <Link
          href={`/tenants/${tenantId}/aops`}
          className="text-sm text-neutral-500 hover:text-neutral-700"
        >
          ← Volver a AOPs
        </Link>
      </div>
      <AopEditView tenantId={tenantId} aopId={aopId} />
    </div>
  )
}
