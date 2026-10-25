'use client'

import { useState } from 'react'
import { useParams } from 'next/navigation'
import { Send } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  useChat,
  useCreateChat,
  useSendChatMessage,
  type ChatAgentEntry,
  type ChatEntry,
} from '@/lib/api/hooks/probar-agente'

function formatUsd(cents: number): string {
  return `$${(cents / 100).toFixed(4)}`
}

function DecisionBadge({ entry }: { entry: ChatAgentEntry }) {
  if (entry.decision === 'escalate') {
    return <Badge variant="warning">Escaló</Badge>
  }
  if (entry.decision === 'error') {
    return <Badge variant="danger">Error</Badge>
  }
  return <Badge variant="success">Respondió</Badge>
}

function AgentTurnMeta({ entry }: { entry: ChatAgentEntry }) {
  return (
    <div className="mt-2 space-y-1 text-xs text-foreground-muted">
      <div className="flex flex-wrap items-center gap-2">
        <DecisionBadge entry={entry} />
        <span>{formatUsd(entry.cost_cents)}</span>
        {entry.skills.map((skill) => (
          <Badge key={skill} variant="outline">
            {skill}
          </Badge>
        ))}
      </div>
      {entry.escalation_reason && <p>Motivo: {entry.escalation_reason}</p>}
      {entry.error && <p className="text-danger-foreground">Error: {entry.error}</p>}
      {entry.trace_id && (
        <p>
          Traza LangSmith: <code className="select-all">{entry.trace_id}</code>
        </p>
      )}
    </div>
  )
}

function Message({ entry }: { entry: ChatEntry }) {
  const isAgent = entry.role === 'agent'
  return (
    <div className={isAgent ? 'flex justify-start' : 'flex justify-end'}>
      <div
        className={
          isAgent
            ? 'max-w-[80%] rounded-lg rounded-tl-sm border border-border bg-surface px-3 py-2 text-sm'
            : 'max-w-[80%] rounded-lg rounded-tr-sm bg-accent px-3 py-2 text-sm text-foreground-on-accent'
        }
      >
        <p className="whitespace-pre-wrap leading-relaxed">
          {entry.content || (isAgent ? '(sin respuesta)' : '')}
        </p>
        {isAgent && <AgentTurnMeta entry={entry as ChatAgentEntry} />}
      </div>
    </div>
  )
}

export default function ProbarAgentePage() {
  const { tenantId } = useParams<{ tenantId: string }>()
  const [chatId, setChatId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState<string | null>(null)
  const [sessionError, setSessionError] = useState<string | null>(null)

  const createChat = useCreateChat(tenantId)
  const { data: chat } = useChat(tenantId, chatId)
  const sendMessage = useSendChatMessage(tenantId)

  const turns = chat?.turns ?? []
  const busy = createChat.isPending || sendMessage.isPending

  const handleSend = async () => {
    const text = draft.trim()
    if (!text || busy) return
    setSessionError(null)
    setDraft('')
    setPending(text)
    try {
      let id = chatId
      if (!id) {
        const created = await createChat.mutateAsync()
        id = created.id
        setChatId(id)
      }
      await sendMessage.mutateAsync({ chatId: id, text })
    } catch (error) {
      setSessionError((error as Error).message)
    } finally {
      setPending(null)
    }
  }

  const handleNew = () => {
    setChatId(null)
    setDraft('')
    setPending(null)
    setSessionError(null)
  }

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col gap-4 p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold text-foreground">Probar agente</h1>
          <p className="mt-0.5 text-sm text-foreground-muted">
            Chatea con el grafo real de este tenant como lo haría un cliente. No se entrega nada
            a ningún canal y el gasto cuenta en el tope diario del simulador.
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <span className="text-sm text-foreground-muted">
            Coste de la sesión: {formatUsd(chat?.cost_cents ?? 0)}
          </span>
          <Button variant="outline" size="sm" onClick={handleNew} disabled={busy}>
            Nueva conversación
          </Button>
        </div>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto rounded-xl border border-border bg-surface-muted p-4">
        {turns.length === 0 && !pending && (
          <p className="text-sm text-foreground-muted">
            Escribe un mensaje para empezar. Cada conversación nueva parte de cero.
          </p>
        )}
        {turns.map((entry, index) => (
          <Message key={`${entry.turn_number}-${entry.role}-${index}`} entry={entry} />
        ))}
        {pending && (
          <>
            <div className="flex justify-end">
              <div className="max-w-[80%] rounded-lg rounded-tr-sm bg-accent px-3 py-2 text-sm text-foreground-on-accent">
                <p className="whitespace-pre-wrap leading-relaxed">{pending}</p>
              </div>
            </div>
            <p className="text-xs text-foreground-muted">El agente está pensando…</p>
          </>
        )}
        <div ref={(el) => el?.scrollIntoView({ behavior: 'smooth' })} />
      </div>

      {sessionError && (
        <div
          role="alert"
          className="rounded-lg border border-danger-subtle bg-danger-subtle px-3 py-2 text-sm text-danger-foreground"
        >
          {sessionError}
        </div>
      )}

      <form
        className="flex items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          void handleSend()
        }}
      >
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              void handleSend()
            }
          }}
          rows={2}
          maxLength={4000}
          placeholder="Escribe como un cliente…"
          aria-label="Mensaje del cliente"
          className="min-h-[3rem] flex-1 resize-none rounded-lg border border-border bg-surface px-3 py-2 text-sm"
        />
        <Button type="submit" disabled={busy || !draft.trim()}>
          <Send aria-hidden />
          Enviar
        </Button>
      </form>
    </div>
  )
}
