'use client'

import { useAop } from '@/lib/api/hooks/aops'
import { AopEditor } from './AopEditor'

interface AopEditViewProps {
  tenantId: string
  aopId: string
}

export function AopEditView({ tenantId, aopId }: AopEditViewProps) {
  const { data: aop, isLoading, error } = useAop(tenantId, aopId)

  if (isLoading) {
    return (
      <div className="py-16 text-center text-sm text-neutral-400">Cargando AOP...</div>
    )
  }

  if (error || !aop) {
    return (
      <div className="py-16 text-center text-sm text-red-500">
        {error?.message ?? 'AOP no encontrado.'}
      </div>
    )
  }

  return (
    <AopEditor
      mode="edit"
      tenantId={tenantId}
      aopId={aopId}
      initialSource={aop.raw_source}
      currentVersion={aop.current_version}
      slug={aop.slug}
    />
  )
}
