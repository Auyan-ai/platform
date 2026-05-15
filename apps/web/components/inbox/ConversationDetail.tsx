'use client'

import { useState, useRef, useEffect } from 'react'
import Link from 'next/link'
import { cn } from '@/lib/utils'
import {
  useConversation,
  useReplyMutation,
  useEscalateMutation,
  useCloseMutation,
} from '@/lib/api/hooks/conversations'
import type { components } from '@auyan/shared/api-types'

type ConversationOut = components['schemas']['ConversationOut']
type MessageOut = components['schemas']['MessageOut']

// ----------------------------------------------------------------
// Helpers
// ----------------------------------------------------------------

const ROLE_STYLES: Record<MessageOut['role'], string> = {
  customer: 'self-start bg-neutral-100 text-neutral-800',
  agent_ai: 'self-end bg-blue-50 text-blue-900',
  agent_human: 'self-end bg-neutral-900 text-white',
  system: 'self-center bg-transparent text-neutral-400 text-xs italic',
}

const STATUS_STYLES: Record<ConversationOut['status'], string> = {
  open: 'bg-green-50 text-green-700',
  pending: 'bg-yellow-50 text-yellow-700',
  escalated: 'bg-red-50 text-red-700',
  resolved: 'bg-blue-50 text-blue-700',
  closed: 'bg-neutral-100 text-neutral-500',
}

const STATUS_LABELS: Record<ConversationOut['status'], string> = {
  open: 'Abierta',
  pending: 'Pendiente',
  escalated: 'Escalada',
  resolved: 'Resuelta',
  closed: 'Cerrada',
}

const ROLE_LABELS: Record<MessageOut['role'], string> = {
  customer: 'Cliente',
  agent_ai: 'Agente IA',
  agent_human: 'Agente',
  system: 'Sistema',
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
    <div className={cn('flex flex-col max-w-[75%]', ROLE_STYLES[msg.role])}>
      {!isSystem && (
        <span className="text-[11px] font-medium mb-1 opacity-60">{ROLE_LABELS[msg.role]}</span>
      )}
      <div
        className={cn(
          'rounded-2xl px-4 py-2.5 text-sm whitespace-pre-wrap',
          ROLE_STYLES[msg.role],
        )}
      >
        {msg.content}
      </div>
      <span className="text-[10px] mt-1 opacity-40 self-end">{formatTime(msg.created_at)}</span>
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

  const isClosed = status === 'closed' || status === 'resolved'

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
      <div className="border-t border-neutral-200 px-4 py-3 text-sm text-neutral-400 text-center">
        Conversación {STATUS_LABELS[status].toLowerCase()} — sólo lectura
      </div>
    )
  }

  return (
    <div className="border-t border-neutral-200 p-4 space-y-3">
      {error && (
        <div className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>
      )}

      {escalateMode ? (
        <div className="space-y-2">
          <label className="text-xs font-medium text-neutral-600">Razón del escalado</label>
          <textarea
            autoFocus
            value={escalateReason}
            onChange={(e) => setEscalateReason(e.target.value)}
            placeholder="Describe por qué se escala esta conversación…"
            rows={3}
            className="w-full resize-none rounded-xl border border-neutral-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-neutral-900"
          />
          <div className="flex gap-2 justify-end">
            <button
              onClick={() => {
                setEscalateMode(false)
                setEscalateReason('')
              }}
              className="px-3 py-1.5 text-sm text-neutral-500 hover:text-neutral-900"
            >
              Cancelar
            </button>
            <button
              onClick={handleEscalate}
              disabled={!escalateReason.trim() || escalateMutation.isPending}
              className="px-4 py-1.5 rounded-xl bg-red-600 text-white text-sm font-medium hover:bg-red-700 disabled:opacity-40"
            >
              {escalateMutation.isPending ? 'Escalando…' : 'Confirmar escalado'}
            </button>
          </div>
        </div>
      ) : (
        <>
          <textarea
            ref={textareaRef}
            value={reply}
            onChange={(e) => setReply(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Escribe una respuesta… (Cmd+Enter para enviar)"
            rows={3}
            className="w-full resize-none rounded-xl border border-neutral-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-neutral-900"
          />
          <div className="flex items-center justify-between">
            <div className="flex gap-2">
              {status !== 'escalated' && (
                <button
                  onClick={() => setEscalateMode(true)}
                  className="px-3 py-1.5 rounded-xl border border-red-200 text-red-600 text-sm hover:bg-red-50"
                >
                  Escalar
                </button>
              )}
              <button
                onClick={handleClose}
                disabled={closeMutation.isPending}
                className="px-3 py-1.5 rounded-xl border border-neutral-200 text-neutral-600 text-sm hover:bg-neutral-50 disabled:opacity-40"
              >
                {closeMutation.isPending ? 'Cerrando…' : 'Cerrar'}
              </button>
            </div>
            <button
              onClick={handleReply}
              disabled={!reply.trim() || replyMutation.isPending}
              className="px-4 py-1.5 rounded-xl bg-neutral-900 text-white text-sm font-medium hover:bg-neutral-700 disabled:opacity-40"
            >
              {replyMutation.isPending ? 'Enviando…' : 'Responder'}
            </button>
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
  backHref,
}: {
  tenantId: string
  conversationId: string
  readOnly?: boolean
  backHref?: string
}) {
  const { data, isLoading, isError, error } = useConversation(tenantId, conversationId)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [data?.messages.length])

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center text-sm text-neutral-400">
        Cargando conversación…
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
        Error: {error instanceof Error ? error.message : 'No se pudo cargar la conversación'}
      </div>
    )
  }

  const { conversation, messages } = data

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-neutral-200 px-4 py-3">
        <Link
          href={backHref ?? `/tenants/${tenantId}/conversations`}
          className="text-neutral-400 hover:text-neutral-900 text-sm"
        >
          ← Volver
        </Link>
        <div className="flex-1 min-w-0">
          <h2 className="text-sm font-semibold text-neutral-900 truncate">
            {conversation.subject ?? `Conversación ${conversation.id.slice(0, 8)}`}
          </h2>
          <p className="text-xs text-neutral-400">
            {conversation.channel} · ID {conversation.id.slice(0, 8)}
          </p>
        </div>
        <span
          className={cn(
            'shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium',
            STATUS_STYLES[conversation.status],
          )}
        >
          {STATUS_LABELS[conversation.status]}
        </span>
      </div>

      {/* Message thread */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4 flex flex-col">
        {messages.length === 0 ? (
          <p className="text-center text-sm text-neutral-400 py-8">Sin mensajes aún.</p>
        ) : (
          messages.map((msg) => <MessageBubble key={msg.id} msg={msg} />)
        )}
        <div ref={bottomRef} />
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
        <div className="border-t border-neutral-200 px-4 py-3 text-center text-sm text-neutral-400">
          Vista de solo lectura
        </div>
      )}
    </div>
  )
}
