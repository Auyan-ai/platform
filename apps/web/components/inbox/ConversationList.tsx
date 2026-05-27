'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useConversations } from '@/lib/api/hooks/conversations'
import { cn } from '@/lib/utils'
import { Badge, type BadgeProps } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
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

const STATUS_VARIANT: Record<ConversationStatus, BadgeProps['variant']> = {
  open: 'default', // cobalto = activo/info
  pending: 'warning',
  escalated: 'danger',
  resolved: 'success',
  closed: 'muted',
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

export function ConversationList({
  tenantId,
  basePath,
}: {
  tenantId: string
  basePath?: string
}) {
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
  const resolvedBasePath = basePath ?? `/tenants/${tenantId}/conversations`

  function handleFilterChange(next: string) {
    setActiveStatus(next as ConversationStatus | 'all')
    setOffset(0)
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-foreground">Conversaciones</h1>
        {isLoading && (
          <span className="text-xs text-foreground-muted">Actualizando…</span>
        )}
      </div>

      {/* Filtros de status */}
      <Tabs value={activeStatus} onValueChange={handleFilterChange}>
        <TabsList className="w-full justify-start">
          {STATUS_FILTERS.map((s) => (
            <TabsTrigger key={s} value={s}>
              {STATUS_LABELS[s]}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {/* Contenido */}
      {isError ? (
        <div className="rounded-md bg-danger-subtle px-4 py-3 text-sm text-danger-foreground">
          Error al cargar: {error instanceof Error ? error.message : 'desconocido'}
        </div>
      ) : conversations.length === 0 && !isLoading ? (
        <div className="py-12 text-center text-sm text-foreground-muted">
          No hay conversaciones{' '}
          {activeStatus !== 'all' && `con estado "${STATUS_LABELS[activeStatus]}"`}.
        </div>
      ) : (
        <div className="divide-y divide-border-subtle rounded-md border border-border bg-surface">
          {conversations.map((conv) => (
            <Link
              key={conv.id}
              href={`${resolvedBasePath}/${conv.id}`}
              className={cn(
                'flex items-center gap-3 px-4 py-3 transition-colors',
                'hover:bg-surface-muted',
              )}
            >
              <Badge variant={STATUS_VARIANT[conv.status]}>
                {STATUS_LABELS[conv.status]}
              </Badge>

              <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground-body">
                {conv.subject ?? `Conversación ${conv.id.slice(0, 8)}`}
              </span>

              <span className="shrink-0 text-xs text-foreground-muted">
                {CHANNEL_LABELS[conv.channel]}
              </span>

              <span className="shrink-0 text-xs text-foreground-muted tabular-nums">
                {relativeTime(conv.last_message_at)}
              </span>
            </Link>
          ))}
        </div>
      )}

      {/* Paginación */}
      {(hasPrev || hasMore) && (
        <div className="flex justify-between">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setOffset((o) => Math.max(0, o - LIMIT))}
            disabled={!hasPrev}
          >
            ← Anterior
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setOffset((o) => o + LIMIT)}
            disabled={!hasMore}
          >
            Siguiente →
          </Button>
        </div>
      )}
    </div>
  )
}
