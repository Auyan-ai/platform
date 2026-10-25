'use client'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import type { PlanTier } from '@/lib/api/hooks/tenant-create'
import { usePromoteTenant } from '@/lib/api/hooks/tenant-promote'
import { suggestClientSlug } from '@/lib/demo'
import { UserCheck } from 'lucide-react'
import { useState } from 'react'

const SLUG_PATTERN = /^[a-z][a-z0-9-]{1,49}$/

export function PromoteDemoDialog({
  tenantId,
  tenantName,
}: {
  tenantId: string
  tenantName: string
}) {
  const [open, setOpen] = useState(false)
  const [adminName, setAdminName] = useState('')
  const [adminEmail, setAdminEmail] = useState('')
  const [planTier, setPlanTier] = useState<PlanTier>('founding')
  const [slug, setSlug] = useState(() => suggestClientSlug(tenantName))
  const mutation = usePromoteTenant(tenantId)

  const slugInvalid = slug.length > 0 && !SLUG_PATTERN.test(slug)
  const canSubmit =
    SLUG_PATTERN.test(slug) &&
    adminEmail.includes('@') &&
    adminName.trim().length > 0 &&
    !mutation.isPending

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canSubmit) return
    try {
      await mutation.mutateAsync({
        admin_email: adminEmail.trim(),
        admin_name: adminName.trim(),
        plan_tier: planTier,
        slug,
      })
      setOpen(false)
    } catch {
      // El error queda en mutation.error; el catch evita uncaught promise.
    }
  }

  function handleOpenChange(next: boolean) {
    setOpen(next)
    if (!next) mutation.reset()
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button size="sm">
          <UserCheck className="size-4" />
          Convertir en cliente
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Convertir en cliente</DialogTitle>
          <DialogDescription>
            Invita al admin y quita la caducidad. Se conservan la KB, los datos y el playbook; los
            documentos traídos de la web quedan pendientes de confirmar antes de pasar a shadow.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <Label htmlFor="promote_admin_name">Nombre del tenant_admin</Label>
            <Input
              id="promote_admin_name"
              value={adminName}
              onChange={(e) => setAdminName(e.target.value)}
              placeholder="Ana García"
              required
              className="mt-1.5"
            />
          </div>

          <div>
            <Label htmlFor="promote_admin_email">Email del tenant_admin</Label>
            <Input
              id="promote_admin_email"
              type="email"
              value={adminEmail}
              onChange={(e) => setAdminEmail(e.target.value)}
              placeholder="ana@tienda.com"
              required
              className="mt-1.5"
            />
          </div>

          <div>
            <Label htmlFor="promote_slug">Slug</Label>
            <Input
              id="promote_slug"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              required
              className="mt-1.5"
            />
            {slugInvalid && (
              <p className="mt-1 text-xs text-danger-foreground">
                Solo minúsculas, números y guiones; debe empezar con letra (2–50 chars).
              </p>
            )}
          </div>

          <div>
            <Label htmlFor="promote_plan_tier">Plan</Label>
            <select
              id="promote_plan_tier"
              value={planTier}
              onChange={(e) => setPlanTier(e.target.value as PlanTier)}
              className="mt-1.5 h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
            >
              <option value="founding">founding</option>
              <option value="standard">standard</option>
              <option value="trial">trial</option>
            </select>
          </div>

          {mutation.isError && (
            <div className="rounded-md bg-danger-subtle px-3 py-2 text-xs text-danger-foreground">
              {mutation.error.message}
            </div>
          )}

          <DialogFooter className="gap-2">
            <Button type="button" variant="outline" onClick={() => handleOpenChange(false)}>
              Cancelar
            </Button>
            <Button type="submit" disabled={!canSubmit}>
              {mutation.isPending ? 'Convirtiendo…' : 'Convertir y mandar invite'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
