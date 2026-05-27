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
      <div className="py-16 text-center text-sm text-foreground-muted">Cargando AOP…</div>
    )
  }

  if (error || !aop) {
    return (
      <div className="rounded-md bg-danger-subtle px-4 py-3 text-sm text-danger-foreground">
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
