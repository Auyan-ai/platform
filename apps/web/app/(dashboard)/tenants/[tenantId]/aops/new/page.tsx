import Link from 'next/link'
import { AopEditor } from '@/components/aops/AopEditor'

export default async function NewAopPage({
  params,
}: {
  params: Promise<{ tenantId: string }>
}) {
  const { tenantId } = await params
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
      <AopEditor mode="create" tenantId={tenantId} />
    </div>
  )
}
