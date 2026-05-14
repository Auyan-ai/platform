'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useConversations } from '@/lib/api/hooks/conversations'
import { cn } from '@/lib/utils'
import type { ConversationStatus, ChannelType } from '@auyan/shared'

// ----------------------------------------------------------------
// Helpers
// ----------------------------------------------------------------

const STATUS_LABELS: Record<ConversationStatus | 'all', string> = {
  all: 'Todas',
  open: 'Abiertas',
  pending: 'Pendientes',
  escalated: 'Escaladas',
  resolved: 'Resueltas',
  closed: 'Cerradas',
}

const STATUS_STYLES: Record<ConversationStatus, string> = {
  open: 'bg-green-50 text-green-700',
  pending: 'bg-yellow-50 text-yellow-700',
  escalated: 'bg-red-50 text-red-700',
  resolved: 'bg-blue-50 text-blue-700',
  closed: 'bg-neutral-100 text-neutral-500',
}

const CHANNEL_LABELS: Record<ChannelType, string> = {
  email: 'Email',
  chat: 'Chat',
  widget: 'Widget',
  whatsapp: 'WhatsApp',
  instagram: 'Instagram',
  zendesk: 'Zendesk',
  intercom: 'Intercom',
  chatwoot: 'Chatwoot',
}

function relativeTime(dateStr: string | null | undefined): string {
  if (!dateStr) return ''
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60_000)
  if (mins < 1) return 'ahora'
  if (mins < 60) return `${mins}m`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h`
  return `${Math.floor(hours / 24)}d`
}

const LIMIT = 50
const STATUS_FILTERS: Array<ConversationStatus | 'all'> = [
  'all',
  'open',
  'escalated',
  'pending',
  'resolved',
  'closed',
]

// ----------------------------------------------------------------
// Component
// ----------------------------------------------------------------

export function ConversationList({ tenantId }: { tenantId: string }) {
  const [activeStatus, setActiveStatus] = useState<ConversationStatus | 'all'>('all')
  const [offset, setOffset] = useState(0)

  const status = activeStatus === 'all' ? undefined : activeStatus

  const { data, isLoading, isError, error } = useConversations({
    tenantId,
    status,
    limit: LIMIT,
    offset,
  })

  const conversations = data?.conversations ?? []
  const hasMore = conversations.length === LIMIT
  const hasPrev = offset > 0

  function handleFilterChange(next: ConversationStatus | 'all') {
    setActiveStatus(next)
    setOffset(0)
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-neutral-900">Conversaciones</h1>
        {isLoading && (
          <span className="text-xs text-neutral-400">Actualizando...</span>
        )}
      </div>

      {/* Filtros de status */}
      <div className="flex gap-1 border-b border-neutral-200 pb-0">
        {STATUS_FILTERS.map((s) => (
          <button
            key={s}
            onClick={() => handleFilterChange(s)}
            className={cn(
              'px-3 py-2 text-sm font-medium transition-colors',
              '-mb-px border-b-2',
              activeStatus === s
                ? 'border-neutral-900 text-neutral-900'
                : 'border-transparent text-neutral-500 hover:text-neutral-700',
            )}
          >
            {STATUS_LABELS[s]}
          </button>
        ))}
      </div>

      {/* Contenido */}
      {isError ? (
        <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
          Error al cargar: {error instanceof Error ? error.message : 'desconocido'}
        </div>
      ) : conversations.length === 0 && !isLoading ? (
        <div className="py-12 text-center text-sm text-neutral-400">
          No hay conversaciones {activeStatus !== 'all' && `con estado "${STATUS_LABELS[activeStatus]}"`}.
        </div>
      ) : (
        <div className="divide-y divide-neutral-100 rounded-xl border border-neutral-200 bg-white">
          {conversations.map((conv) => (
            <Link
              key={conv.id}
              href={`/tenants/${tenantId}/conversations/${conv.id}`}
              className="flex items-center gap-3 px-4 py-3 hover:bg-neutral-50 transition-colors"
            >
              {/* Status badge */}
              <span
                className={cn(
                  'shrink-0 rounded-full px-2 py-0.5 text-xs font-medium',
                  STATUS_STYLES[conv.status],
                )}
              >
                {STATUS_LABELS[conv.status]}
              </span>

              {/* Subject */}
              <span className="min-w-0 flex-1 truncate text-sm font-medium text-neutral-800">
                {conv.subject ?? `Conversación ${conv.id.slice(0, 8)}`}
              </span>

              {/* Canal */}
              <span className="shrink-0 text-xs text-neutral-400">
                {CHANNEL_LABELS[conv.channel]}
              </span>

              {/* Tiempo */}
              <span className="shrink-0 text-xs text-neutral-400">
                {relativeTime(conv.last_message_at)}
              </span>
            </Link>
          ))}
        </div>
      )}

      {/* Paginación */}
      {(hasPrev || hasMore) && (
        <div className="flex justify-between">
          <button
            onClick={() => setOffset((o) => Math.max(0, o - LIMIT))}
            disabled={!hasPrev}
            className="text-sm text-neutral-500 hover:text-neutral-900 disabled:opacity-30"
          >
            ← Anterior
          </button>
          <button
            onClick={() => setOffset((o) => o + LIMIT)}
            disabled={!hasMore}
            className="text-sm text-neutral-500 hover:text-neutral-900 disabled:opacity-30"
          >
            Siguiente →
          </button>
        </div>
      )}
    </div>
  )
}
