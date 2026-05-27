'use client'

import Link from 'next/link'
import { Plus } from 'lucide-react'
import { useAops, useToggleAop, useDeleteAop, type AopWorkspace } from '@/lib/api/hooks/aops'
import { cn } from '@/lib/utils'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

interface AopListProps {
  tenantId: string
}

const WORKSPACE_TABS: AopWorkspace[] = ['production', 'staging']

export function AopList({ tenantId }: AopListProps) {
  const [workspace, setWorkspace] = useState<AopWorkspace>('production')
  const { data: aops, isLoading, error } = useAops(tenantId, workspace)
  const toggleMut = useToggleAop(tenantId, workspace)
  const deleteMut = useDeleteAop(tenantId, workspace)

  function handleToggle(aopId: string, current: boolean) {
    toggleMut.mutate({ aopId, is_active: !current })
  }

  function handleDelete(aopId: string, slug: string) {
    if (!confirm(`¿Eliminar el AOP "${slug}"? Esta acción no se puede deshacer.`)) return
    deleteMut.mutate(aopId)
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-foreground">Agent Operating Procedures</h1>
          <p className="text-sm text-foreground-muted mt-0.5">
            Procedimientos que guían el comportamiento del agente por intent
          </p>
        </div>
        <Button asChild size="sm">
          <Link href={`/tenants/${tenantId}/aops/new`}>
            <Plus className="size-4" />
            Nuevo AOP
          </Link>
        </Button>
      </div>

      <Tabs
        value={workspace}
        onValueChange={(v) => setWorkspace(v as AopWorkspace)}
        className="mb-4"
      >
        <TabsList className="w-full justify-start">
          {WORKSPACE_TABS.map((ws) => (
            <TabsTrigger key={ws} value={ws}>
              {ws === 'production' ? 'Producción' : 'Staging'}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {isLoading && (
        <div className="py-12 text-center text-sm text-foreground-muted">
          Cargando AOPs…
        </div>
      )}
      {error && (
        <div className="rounded-md bg-danger-subtle px-4 py-3 text-sm text-danger-foreground">
          Error al cargar AOPs: {error.message}
        </div>
      )}
      {!isLoading && !error && aops?.length === 0 && (
        <div className="py-16 text-center space-y-3">
          <p className="text-foreground-muted text-sm">No hay AOPs en {workspace}.</p>
          <Button asChild variant="link" size="sm">
            <Link href={`/tenants/${tenantId}/aops/new`}>Crear el primero</Link>
          </Button>
        </div>
      )}
      {aops && aops.length > 0 && (
        <div className="rounded-md border border-border divide-y divide-border-subtle bg-surface overflow-hidden">
          {aops.map((aop) => (
            <div key={aop.id} className="flex items-center gap-4 px-4 py-3">
              <span
                className={cn(
                  'h-2 w-2 rounded-full flex-shrink-0',
                  aop.is_active ? 'bg-success' : 'bg-border-strong',
                )}
                aria-label={aop.is_active ? 'Activo' : 'Inactivo'}
              />

              <div className="flex-1 min-w-0">
                <Link
                  href={`/tenants/${tenantId}/aops/${aop.id}`}
                  className="text-sm font-medium text-foreground hover:underline truncate block"
                >
                  {aop.name}
                </Link>
                <div className="flex items-center gap-2 mt-0.5">
                  <code className="text-xs text-foreground-muted font-mono">{aop.slug}</code>
                  {aop.description && (
                    <span className="text-xs text-foreground-muted truncate">
                      {aop.description}
                    </span>
                  )}
                </div>
              </div>

              <span className="text-xs text-foreground-muted flex-shrink-0 tabular-nums font-mono">
                v{aop.current_version}
              </span>

              <div className="flex items-center gap-2 flex-shrink-0">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handleToggle(aop.id, aop.is_active)}
                  disabled={toggleMut.isPending}
                  className={cn(
                    'text-xs h-7',
                    !aop.is_active && 'border-success-subtle text-success-foreground hover:bg-success-subtle',
                  )}
                >
                  {aop.is_active ? 'Desactivar' : 'Activar'}
                </Button>
                <Button asChild variant="outline" size="sm" className="text-xs h-7">
                  <Link href={`/tenants/${tenantId}/aops/${aop.id}`}>Editar</Link>
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handleDelete(aop.id, aop.slug)}
                  disabled={deleteMut.isPending}
                  className="text-xs h-7 border-danger-subtle text-danger-foreground hover:bg-danger-subtle"
                >
                  Eliminar
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
