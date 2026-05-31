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
import { useCreateTenant, type CreateTenantInput, type PlanTier } from '@/lib/api/hooks/tenant-create'
import { Plus } from 'lucide-react'
import Link from 'next/link'
import { useState } from 'react'

const SLUG_PATTERN = /^[a-z][a-z0-9-]{1,49}$/

function suggestSlug(name: string): string {
  return name
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 50)
}

export function CreateTenantDialog() {
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<CreateTenantInput>({
    company_name: '',
    slug: '',
    plan_tier: 'founding',
    tenant_admin_email: '',
    tenant_admin_name: '',
  })
  const [slugTouched, setSlugTouched] = useState(false)
  const mutation = useCreateTenant()

  const slugInvalid = form.slug.length > 0 && !SLUG_PATTERN.test(form.slug)
  const canSubmit =
    form.company_name.length > 0 &&
    SLUG_PATTERN.test(form.slug) &&
    form.tenant_admin_email.includes('@') &&
    form.tenant_admin_name.length > 0 &&
    !mutation.isPending

  function update<K extends keyof CreateTenantInput>(key: K, value: CreateTenantInput[K]) {
    setForm((prev) => {
      const next = { ...prev, [key]: value }
      if (key === 'company_name' && !slugTouched) {
        next.slug = suggestSlug(String(value))
      }
      return next
    })
  }

  function reset() {
    setForm({
      company_name: '',
      slug: '',
      plan_tier: 'founding',
      tenant_admin_email: '',
      tenant_admin_name: '',
    })
    setSlugTouched(false)
    mutation.reset()
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canSubmit) return
    try {
      await mutation.mutateAsync(form)
    } catch {
      // El error queda en mutation.error; el catch evita uncaught promise.
    }
  }

  function handleOpenChange(next: boolean) {
    setOpen(next)
    if (!next) reset()
  }

  const result = mutation.data

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button>
          <Plus className="size-4" />
          Nuevo cliente
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Nuevo cliente</DialogTitle>
          <DialogDescription>
            Crea el tenant y manda magic link al tenant_admin para que entre al portal de onboarding.
          </DialogDescription>
        </DialogHeader>

        {result ? (
          <div className="space-y-3">
            <div className="rounded-md bg-success-subtle px-3 py-2 text-sm text-success-foreground">
              Tenant <strong>{result.tenant.name}</strong> creado.{' '}
              {result.invite_sent
                ? 'Invite enviado al tenant_admin.'
                : 'Invite NO enviado — revisar Supabase Auth.'}
            </div>
            <div className="rounded-md border border-border-subtle px-3 py-2 text-xs text-foreground-muted">
              <p>
                <span className="font-medium text-foreground">slug:</span> {result.tenant.slug}
              </p>
              <p>
                <span className="font-medium text-foreground">lifecycle:</span>{' '}
                {result.tenant.agent_lifecycle_state}
              </p>
              <p>
                <span className="font-medium text-foreground">plan:</span> {result.tenant.plan_tier}
              </p>
            </div>
            <DialogFooter className="gap-2">
              <Button variant="outline" onClick={() => handleOpenChange(false)}>
                Cerrar
              </Button>
              <Button asChild>
                <Link href={`/clients/${result.tenant.id}/onboarding`}>Ver onboarding</Link>
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <Label htmlFor="company_name">Nombre comercial</Label>
              <Input
                id="company_name"
                value={form.company_name}
                onChange={(e) => update('company_name', e.target.value)}
                placeholder="Lunaria"
                required
                className="mt-1.5"
              />
            </div>

            <div>
              <Label htmlFor="slug">Slug</Label>
              <Input
                id="slug"
                value={form.slug}
                onChange={(e) => {
                  setSlugTouched(true)
                  update('slug', e.target.value)
                }}
                placeholder="lunaria"
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
              <Label htmlFor="plan_tier">Plan</Label>
              <select
                id="plan_tier"
                value={form.plan_tier}
                onChange={(e) => update('plan_tier', e.target.value as PlanTier)}
                className="mt-1.5 h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
              >
                <option value="founding">founding</option>
                <option value="standard">standard</option>
                <option value="trial">trial</option>
              </select>
            </div>

            <div>
              <Label htmlFor="admin_name">Nombre del tenant_admin</Label>
              <Input
                id="admin_name"
                value={form.tenant_admin_name}
                onChange={(e) => update('tenant_admin_name', e.target.value)}
                placeholder="Ana García"
                required
                className="mt-1.5"
              />
            </div>

            <div>
              <Label htmlFor="admin_email">Email del tenant_admin</Label>
              <Input
                id="admin_email"
                type="email"
                value={form.tenant_admin_email}
                onChange={(e) => update('tenant_admin_email', e.target.value)}
                placeholder="ana@lunaria.com"
                required
                className="mt-1.5"
              />
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
                {mutation.isPending ? 'Creando…' : 'Crear y mandar invite'}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}
