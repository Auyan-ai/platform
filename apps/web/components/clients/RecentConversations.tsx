'use client'

import Link from 'next/link'
import { useConversations } from '@/lib/api/hooks/conversations'
import { cn } from '@/lib/utils'
import type { ConversationStatus, ChannelType } from '@auyan/shared'

const STATUS_LABELS: Record<ConversationStatus, string> = {
  open: 'Abierta',
  pending: 'Pendiente',
  escalated: 'Escalada',
  resolved: 'Resuelta',
  closed: 'Cerrada',
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

interface RecentConversationsProps {
  tenantId: string
}

export function RecentConversations({ tenantId }: RecentConversationsProps) {
  const { data, isLoading, isError } = useConversations({ tenantId, limit: 10, offset: 0 })
  const conversations = data?.conversations ?? []

  if (isLoading) {
    return (
      <div className="space-y-2">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="h-12 animate-pulse rounded-lg bg-neutral-100" />
        ))}
      </div>
    )
  }

  if (isError) {
    return (
      <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
        No se pudieron cargar las conversaciones recientes.
      </div>
    )
  }

  if (conversations.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-neutral-400">
        No hay conversaciones aún.
      </p>
    )
  }

  return (
    <div className="divide-y divide-neutral-100 rounded-xl border border-neutral-200 bg-white">
      {conversations.map((conv) => (
        <Link
          key={conv.id}
          href={`/clients/${tenantId}/conversations/${conv.id}`}
          className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-neutral-50"
        >
          <span
            className={cn(
              'shrink-0 rounded-full px-2 py-0.5 text-xs font-medium',
              STATUS_STYLES[conv.status],
            )}
          >
            {STATUS_LABELS[conv.status]}
          </span>
          <span className="min-w-0 flex-1 truncate text-sm font-medium text-neutral-800">
            {conv.subject ?? `Conversación ${conv.id.slice(0, 8)}`}
          </span>
          <span className="shrink-0 text-xs text-neutral-400">
            {CHANNEL_LABELS[conv.channel]}
          </span>
          <span className="shrink-0 text-xs text-neutral-400">
            {relativeTime(conv.last_message_at)}
          </span>
        </Link>
      ))}
    </div>
  )
}
