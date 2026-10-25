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
import { useCreateDemo } from '@/lib/api/hooks/tenant-demo'
import { Sparkles } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useState } from 'react'

export function NewDemoDialog() {
  const [open, setOpen] = useState(false)
  const [url, setUrl] = useState('')
  const router = useRouter()
  const mutation = useCreateDemo()

  const canSubmit = url.trim().length > 2 && !mutation.isPending

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canSubmit) return
    try {
      const tenant = await mutation.mutateAsync({ url: url.trim() })
      setOpen(false)
      router.push(`/tenants/${tenant.id}/knowledge`)
    } catch {
      // El error queda en mutation.error; el catch evita uncaught promise.
    }
  }

  function handleOpenChange(next: boolean) {
    setOpen(next)
    if (!next) {
      setUrl('')
      mutation.reset()
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button variant="secondary">
          <Sparkles className="size-4" />
          Nueva demo
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Nueva demo</DialogTitle>
          <DialogDescription>
            Crea un tenant de demo desde la URL de la tienda. No tiene admin ni canales, solo skills
            de lectura, y caduca solo.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <Label htmlFor="demo_url">URL de la tienda</Label>
            <Input
              id="demo_url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://www.thinkingmu.com"
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
              {mutation.isPending ? 'Creando…' : 'Crear demo'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
