'use client'

import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import {
  useConfirmKbDocuments,
  useTenantOnboardingChecklist,
  useUnconfirmedKbDocuments,
} from '@/lib/api/hooks/tenant-context'
import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import { useState } from 'react'

/** Aviso al cliente de lo que la demo trajo de su web y aún no confirmó (ADR 0015 §6). */
export function PendingConfirmationBanner({ tenantId }: { tenantId: string }) {
  const [reviewing, setReviewing] = useState(false)
  const { data: checklist } = useTenantOnboardingChecklist(tenantId)
  const pending = checklist?.unconfirmed_kb_documents ?? 0
  const { data: documents, isLoading } = useUnconfirmedKbDocuments(tenantId, reviewing && pending > 0)
  const confirm = useConfirmKbDocuments(tenantId)

  if (!checklist || pending === 0) return null

  return (
    <Card className="space-y-3 border-warning-foreground/30 bg-warning-subtle p-(--density-card-p)">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-start gap-2">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning-foreground" />
          <div>
            <p className="text-sm font-medium text-foreground">
              {pending === 1
                ? '1 documento traído de tu web pendiente de confirmar'
                : `${pending} documentos traídos de tu web pendientes de confirmar`}
            </p>
            <p className="text-xs text-foreground-muted">
              El agente no puede pasar a shadow ni a activo hasta que los confirmes.
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => setReviewing((value) => !value)}>
            {reviewing ? 'Ocultar' : 'Revisar'}
          </Button>
          <Button
            size="sm"
            disabled={confirm.isPending}
            onClick={() => confirm.mutate({ all: true })}
          >
            <CheckCircle2 className="size-4" />
            {confirm.isPending ? 'Confirmando…' : 'Confirmar todo'}
          </Button>
        </div>
      </div>

      {confirm.isError && (
        <div className="rounded-md bg-danger-subtle px-3 py-2 text-xs text-danger-foreground">
          {confirm.error.message}
        </div>
      )}

      {reviewing && (
        <ul className="divide-y divide-border-subtle rounded-md border border-border-subtle bg-background">
          {isLoading && <li className="px-3 py-2 text-xs text-foreground-muted">Cargando…</li>}
          {(documents ?? []).map((doc) => (
            <li key={doc.id} className="flex items-center justify-between gap-3 px-3 py-2">
              <div className="min-w-0">
                <p className="truncate text-sm text-foreground">{doc.title}</p>
                {doc.source && (
                  <p className="truncate text-xs text-foreground-muted">{doc.source}</p>
                )}
              </div>
              <Button
                variant="ghost"
                size="sm"
                disabled={confirm.isPending}
                onClick={() => confirm.mutate({ documentIds: [doc.id] })}
              >
                Confirmar
              </Button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}
