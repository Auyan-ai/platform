'use client'

import Link from 'next/link'
import { useAops, useToggleAop, useDeleteAop, type AopWorkspace } from '@/lib/api/hooks/aops'
import { cn } from '@/lib/utils'
import { useState } from 'react'

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
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-neutral-900">Agent Operating Procedures</h1>
          <p className="text-sm text-neutral-500 mt-0.5">
            Procedimientos que guían el comportamiento del agente por intent
          </p>
        </div>
        <Link
          href={`/tenants/${tenantId}/aops/new`}
          className="rounded-lg bg-neutral-900 px-3 py-2 text-sm font-medium text-white hover:bg-neutral-700 transition-colors"
        >
          + Nuevo AOP
        </Link>
      </div>

      {/* Workspace tabs */}
      <div className="flex gap-1 mb-4 border-b border-neutral-200">
        {WORKSPACE_TABS.map((ws) => (
          <button
            key={ws}
            onClick={() => setWorkspace(ws)}
            className={cn(
              'px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors',
              workspace === ws
                ? 'border-neutral-900 text-neutral-900'
                : 'border-transparent text-neutral-500 hover:text-neutral-700',
            )}
          >
            {ws === 'production' ? 'Producción' : 'Staging'}
          </button>
        ))}
      </div>

      {/* Content */}
      {isLoading && (
        <div className="py-12 text-center text-sm text-neutral-400">Cargando AOPs...</div>
      )}
      {error && (
        <div className="py-12 text-center text-sm text-red-500">
          Error al cargar AOPs: {error.message}
        </div>
      )}
      {!isLoading && !error && aops?.length === 0 && (
        <div className="py-16 text-center">
          <p className="text-neutral-500 text-sm">No hay AOPs en {workspace}.</p>
          <Link
            href={`/tenants/${tenantId}/aops/new`}
            className="mt-3 inline-block text-sm text-neutral-900 underline underline-offset-2"
          >
            Crear el primero
          </Link>
        </div>
      )}
      {aops && aops.length > 0 && (
        <div className="rounded-lg border border-neutral-200 divide-y divide-neutral-100 bg-white overflow-hidden">
          {aops.map((aop) => (
            <div key={aop.id} className="flex items-center gap-4 px-4 py-3">
              {/* Status dot */}
              <span
                className={cn(
                  'h-2 w-2 rounded-full flex-shrink-0',
                  aop.is_active ? 'bg-green-500' : 'bg-neutral-300',
                )}
              />

              {/* Info */}
              <div className="flex-1 min-w-0">
                <Link
                  href={`/tenants/${tenantId}/aops/${aop.id}`}
                  className="text-sm font-medium text-neutral-900 hover:underline truncate block"
                >
                  {aop.name}
                </Link>
                <div className="flex items-center gap-2 mt-0.5">
                  <code className="text-xs text-neutral-400">{aop.slug}</code>
                  {aop.description && (
                    <span className="text-xs text-neutral-400 truncate">{aop.description}</span>
                  )}
                </div>
              </div>

              {/* Version badge */}
              <span className="text-xs text-neutral-400 flex-shrink-0">v{aop.current_version}</span>

              {/* Actions */}
              <div className="flex items-center gap-2 flex-shrink-0">
                <button
                  onClick={() => handleToggle(aop.id, aop.is_active)}
                  disabled={toggleMut.isPending}
                  className={cn(
                    'text-xs px-2 py-1 rounded border transition-colors',
                    aop.is_active
                      ? 'border-neutral-200 text-neutral-600 hover:border-neutral-300'
                      : 'border-green-200 text-green-700 hover:border-green-300',
                  )}
                >
                  {aop.is_active ? 'Desactivar' : 'Activar'}
                </button>
                <Link
                  href={`/tenants/${tenantId}/aops/${aop.id}`}
                  className="text-xs px-2 py-1 rounded border border-neutral-200 text-neutral-600 hover:border-neutral-300 transition-colors"
                >
                  Editar
                </Link>
                <button
                  onClick={() => handleDelete(aop.id, aop.slug)}
                  disabled={deleteMut.isPending}
                  className="text-xs px-2 py-1 rounded border border-red-100 text-red-500 hover:border-red-200 transition-colors"
                >
                  Eliminar
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
