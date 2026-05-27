'use client'

import Link from 'next/link'
import { useConversations } from '@/lib/api/hooks/conversations'
import { Badge, type BadgeProps } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import type { ConversationStatus, ChannelType } from '@auyan/shared'

const STATUS_LABELS: Record<ConversationStatus, string> = {
  open: 'Abierta',
  pending: 'Pendiente',
  escalated: 'Escalada',
  resolved: 'Resuelta',
  closed: 'Cerrada',
  closed_abandoned: 'Abandonada',
}

const STATUS_VARIANT: Record<ConversationStatus, BadgeProps['variant']> = {
  open: 'default',
  pending: 'warning',
  escalated: 'danger',
  resolved: 'success',
  closed: 'muted',
  closed_abandoned: 'muted',
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

const SKELETON_ROWS = ['recent-1', 'recent-2', 'recent-3', 'recent-4', 'recent-5']

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

interface RecentConversationsProps {
  tenantId: string
}

export function RecentConversations({ tenantId }: RecentConversationsProps) {
  const { data, isLoading, isError } = useConversations({ tenantId, limit: 10, offset: 0 })
  const conversations = data?.conversations ?? []

  if (isLoading) {
    return (
      <div className="space-y-2">
        {SKELETON_ROWS.map((row) => (
          <Skeleton key={row} className="h-12" />
        ))}
      </div>
    )
  }

  if (isError) {
    return (
      <div className="rounded-md bg-danger-subtle px-4 py-3 text-sm text-danger-foreground">
        No se pudieron cargar las conversaciones recientes.
      </div>
    )
  }

  if (conversations.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-foreground-muted">
        No hay conversaciones aún.
      </p>
    )
  }

  return (
    <div className="divide-y divide-border-subtle rounded-md border border-border bg-surface">
      {conversations.map((conv) => (
        <Link
          key={conv.id}
          href={`/clients/${tenantId}/conversations/${conv.id}`}
          className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-surface-muted"
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
  )
}
