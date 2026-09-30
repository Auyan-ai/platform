'use client'

import { useState, useRef, useEffect } from 'react'
import Link from 'next/link'
import { ArrowLeft } from 'lucide-react'
import { cn } from '@/lib/utils'
import {
  useConversation,
  useReplyMutation,
  useEscalateMutation,
  useCloseMutation,
} from '@/lib/api/hooks/conversations'
import { AgentReasoningPanel } from '@/components/reasoning/AgentReasoningPanel'
import { Badge, type BadgeProps } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import type { components } from '@auyan/shared/api-types'

type ConversationOut = components['schemas']['ConversationOut']
type MessageOut = components['schemas']['MessageOut']
type HandoffOut = components['schemas']['HandoffOut']

// ----------------------------------------------------------------
// Helpers
// ----------------------------------------------------------------

const BUBBLE_STYLES: Record<MessageOut['role'], string> = {
  customer: 'self-start bg-surface-muted text-foreground',
  agent_ai: 'self-end bg-accent-subtle text-accent-foreground',
  agent_human: 'self-end bg-foreground text-foreground-on-accent',
  system: 'self-center bg-transparent text-foreground-muted text-xs italic',
}

const STATUS_VARIANT: Record<ConversationOut['status'], BadgeProps['variant']> = {
  open: 'default',
  pending: 'warning',
  escalated: 'danger',
  resolved: 'success',
  closed: 'muted',
  closed_abandoned: 'muted',
}

const STATUS_LABELS: Record<ConversationOut['status'], string> = {
  open: 'Abierta',
  pending: 'Pendiente',
  escalated: 'Escalada',
  resolved: 'Resuelta',
  closed: 'Cerrada',
  closed_abandoned: 'Abandonada',
}

const ROLE_LABELS: Record<MessageOut['role'], string> = {
  customer: 'Cliente',
  agent_ai: 'Agente IA',
  agent_human: 'Agente',
  system: 'Sistema',
}

const CHANNEL_LABELS: Record<ConversationOut['channel'], string> = {
  email: 'Email',
  chat: 'Chat',
  widget: 'Widget',
  whatsapp: 'WhatsApp',
  instagram: 'Instagram',
  zendesk: 'Zendesk',
  gorgias: 'Gorgias',
  intercom: 'Intercom',
  chatwoot: 'Chatwoot',
}

// Dónde escribió el equipo de la marca cuando no es un usuario de Auyan.
const EXTERNAL_AUTHOR_SOURCES: Record<string, string> = {
  zendesk: 'Zendesk',
  gorgias: 'Gorgias',
  chatwoot: 'Chatwoot',
  whatsapp_business_app: 'móvil',
  zernio_inbox: 'Zernio',
}

const ATTACHMENT_KIND_LABELS: Record<string, string> = {
  image: 'Imagen',
  audio: 'Nota de voz',
  video: 'Vídeo',
  file: 'Archivo',
  sticker: 'Sticker',
}

const DELIVERY_NOTES: Record<string, string> = {
  pending_window: 'Pendiente: se entrega cuando el cliente vuelva a escribir',
  failed: 'No entregado',
}

function authorLabel(msg: MessageOut): string {
  const provider = msg.external_author?.provider
  if (msg.role === 'agent_human' && provider) {
    return `Equipo de la marca (${EXTERNAL_AUTHOR_SOURCES[provider] ?? provider})`
  }
  return ROLE_LABELS[msg.role]
}

function formatTime(dateStr: string): string {
  return new Intl.DateTimeFormat('es', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(dateStr))
}

// ----------------------------------------------------------------
// Message bubble
// ----------------------------------------------------------------

function MessageBubble({ msg }: { msg: MessageOut }) {
  const isSystem = msg.role === 'system'
  return (
    <div className={cn('flex flex-col max-w-[75%]', BUBBLE_STYLES[msg.role])}>
      {!isSystem && (
        <span className="text-[11px] font-medium mb-1 opacity-60">{authorLabel(msg)}</span>
      )}
      <div
        className={cn(
          'rounded-lg px-4 py-2.5 text-sm whitespace-pre-wrap',
          BUBBLE_STYLES[msg.role],
        )}
      >
        {msg.content}
        {msg.attachments && msg.attachments.length > 0 && (
          <ul className="mt-2 space-y-0.5 text-xs opacity-80">
            {msg.attachments.map((att) => (
              <li key={att.filename}>
                📎 {ATTACHMENT_KIND_LABELS[att.kind] ?? att.kind} · {att.filename}
              </li>
            ))}
          </ul>
        )}
      </div>
      <span className="text-[10px] mt-1 opacity-40 self-end tabular-nums">
        {formatTime(msg.created_at)}
        {msg.delivery && DELIVERY_NOTES[msg.delivery] ? ` · ${DELIVERY_NOTES[msg.delivery]}` : ''}
      </span>
    </div>
  )
}

// ----------------------------------------------------------------
// Handoff (un humano de la marca lleva la conversación: la IA calla)
// ----------------------------------------------------------------

function HandoffBanner({ handoff }: { handoff: HandoffOut }) {
  const text =
    handoff.target === 'helpdesk'
      ? `La atiende el equipo de la marca en ${
          EXTERNAL_AUTHOR_SOURCES[handoff.helpdesk_provider ?? ''] ?? handoff.helpdesk_provider
        }${handoff.external_ticket_id ? ` (ticket #${handoff.external_ticket_id})` : ''}. Auyan no responde hasta que se resuelva.`
      : `La marca contestó desde el móvil. Auyan no responde${
          handoff.expires_at ? ` hasta las ${formatTime(handoff.expires_at)}` : ''
        }.`
  return (
    <div className="border-b border-border bg-warning-subtle px-4 py-2 text-xs text-warning-foreground">
      {text}
    </div>
  )
}

// ----------------------------------------------------------------
// Composer
// ----------------------------------------------------------------

function Composer({
  tenantId,
  conversationId,
  status,
}: {
  tenantId: string
  conversationId: string
  status: ConversationOut['status']
}) {
  const [reply, setReply] = useState('')
  const [escalateMode, setEscalateMode] = useState(false)
  const [escalateReason, setEscalateReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const replyMutation = useReplyMutation(tenantId, conversationId)
  const escalateMutation = useEscalateMutation(tenantId, conversationId)
  const closeMutation = useCloseMutation(tenantId, conversationId)

  const isClosed = status === 'closed' || status === 'closed_abandoned' || status === 'resolved'

  async function handleReply() {
    if (!reply.trim()) return
    setError(null)
    const content = reply.trim()
    setReply('')
    try {
      await replyMutation.mutateAsync(content)
    } catch (e) {
      setReply(content)
      setError(e instanceof Error ? e.message : 'Error al enviar respuesta')
    }
  }

  async function handleEscalate() {
    if (!escalateReason.trim()) return
    setError(null)
    try {
      await escalateMutation.mutateAsync(escalateReason.trim())
      setEscalateMode(false)
      setEscalateReason('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al escalar')
    }
  }

  async function handleClose() {
    setError(null)
    try {
      await closeMutation.mutateAsync()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al cerrar')
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      handleReply()
    }
  }

  if (isClosed) {
    return (
      <div className="border-t border-border px-4 py-3 text-sm text-foreground-muted text-center">
        Conversación {STATUS_LABELS[status].toLowerCase()} — sólo lectura
      </div>
    )
  }

  return (
    <div className="border-t border-border p-4 space-y-3">
      {error && (
        <div className="rounded-md bg-danger-subtle px-3 py-2 text-xs text-danger-foreground">
          {error}
        </div>
      )}

      {escalateMode ? (
        <div className="space-y-2">
          <Label htmlFor="escalate-reason">Razón del escalado</Label>
          <Textarea
            id="escalate-reason"
            autoFocus
            value={escalateReason}
            onChange={(e) => setEscalateReason(e.target.value)}
            placeholder="Describe por qué se escala esta conversación…"
            rows={3}
          />
          <div className="flex gap-2 justify-end">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setEscalateMode(false)
                setEscalateReason('')
              }}
            >
              Cancelar
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={handleEscalate}
              disabled={!escalateReason.trim() || escalateMutation.isPending}
            >
              {escalateMutation.isPending ? 'Escalando…' : 'Confirmar escalado'}
            </Button>
          </div>
        </div>
      ) : (
        <>
          <Textarea
            ref={textareaRef}
            value={reply}
            onChange={(e) => setReply(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Escribe una respuesta… (Cmd+Enter para enviar)"
            rows={3}
          />
          <div className="flex items-center justify-between">
            <div className="flex gap-2">
              {status !== 'escalated' && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setEscalateMode(true)}
                  className="border-danger-subtle text-danger-foreground hover:bg-danger-subtle"
                >
                  Escalar
                </Button>
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={handleClose}
                disabled={closeMutation.isPending}
              >
                {closeMutation.isPending ? 'Cerrando…' : 'Cerrar'}
              </Button>
            </div>
            <Button
              size="sm"
              onClick={handleReply}
              disabled={!reply.trim() || replyMutation.isPending}
            >
              {replyMutation.isPending ? 'Enviando…' : 'Responder'}
            </Button>
          </div>
        </>
      )}
    </div>
  )
}

// ----------------------------------------------------------------
// Main component
// ----------------------------------------------------------------

export function ConversationDetail({
  tenantId,
  conversationId,
  readOnly = false,
  maskPII = false,
  backHref,
}: {
  tenantId: string
  conversationId: string
  readOnly?: boolean
  maskPII?: boolean
  backHref?: string
}) {
  const { data, isLoading, isError, error } = useConversation(tenantId, conversationId)
  const bottomRef = useRef<HTMLDivElement>(null)
  const messageCount = data?.messages.length ?? 0

  const isActive =
    data?.conversation.status === 'open' || data?.conversation.status === 'pending'

  useEffect(() => {
    if (messageCount === 0) return
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messageCount])

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center text-sm text-foreground-muted">
        Cargando conversación…
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="rounded-md bg-danger-subtle px-4 py-3 text-sm text-danger-foreground">
        Error: {error instanceof Error ? error.message : 'No se pudo cargar la conversación'}
      </div>
    )
  }

  const { conversation, messages } = data
  const handoff = data.active_handoff ?? null

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-border px-4 py-3">
        <Link
          href={backHref ?? `/tenants/${tenantId}/conversations`}
          className="flex items-center gap-1 text-foreground-muted hover:text-foreground text-sm transition-colors"
        >
          <ArrowLeft className="size-4" />
          Volver
        </Link>
        <div className="flex-1 min-w-0">
          <h2 className="text-sm font-semibold text-foreground truncate">
            {conversation.subject ?? `Conversación ${conversation.id.slice(0, 8)}`}
          </h2>
          <p className="text-xs text-foreground-muted">
            {CHANNEL_LABELS[conversation.channel]} · ID {conversation.id.slice(0, 8)}
          </p>
        </div>
        {conversation.channel === 'whatsapp' && <Badge variant="success">WhatsApp</Badge>}
        <Badge variant={STATUS_VARIANT[conversation.status]}>
          {STATUS_LABELS[conversation.status]}
        </Badge>
      </div>
      {handoff && <HandoffBanner handoff={handoff} />}

      {/* Message thread */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4 flex flex-col">
        {messages.length === 0 ? (
          <p className="text-center text-sm text-foreground-muted py-8">Sin mensajes aún.</p>
        ) : (
          messages.map((msg) => <MessageBubble key={msg.id} msg={msg} />)
        )}
        <div ref={bottomRef} />
      </div>

      {/* Agent reasoning panel */}
      <div className="border-t border-border px-4 py-3">
        <AgentReasoningPanel
          tenantId={tenantId}
          conversationId={conversationId}
          isActive={isActive}
          maskPII={maskPII}
        />
      </div>

      {/* Composer — oculto en modo read-only */}
      {!readOnly && (
        <Composer
          tenantId={tenantId}
          conversationId={conversationId}
          status={conversation.status}
        />
      )}
      {readOnly && (
        <div className="border-t border-border px-4 py-3 text-center text-sm text-foreground-muted">
          Vista de solo lectura
        </div>
      )}
    </div>
  )
}
