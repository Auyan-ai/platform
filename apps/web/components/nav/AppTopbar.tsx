import { Bell, Search, Settings2, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface AppTopbarProps {
  label: string
  actionLabel?: string
}

export function AppTopbar({ label, actionLabel = 'Acción rápida' }: AppTopbarProps) {
  return (
    <header className="fixed left-[200px] right-0 top-0 z-40 flex h-14 items-center gap-4 border-b border-border bg-surface/95 px-6 backdrop-blur">
      <div className="flex min-w-0 flex-1 items-center gap-3 px-0 py-2 text-sm text-foreground-muted">
        <Search className="size-3.5 shrink-0" />
        <span className="truncate">Buscar conversaciones, clientes, AOPs...</span>
        <kbd className="ml-auto hidden rounded-xs border border-border bg-surface px-1.5 py-0.5 text-[10px] font-medium text-foreground-muted md:inline">
          K
        </kbd>
      </div>

      <Button variant="secondary" size="sm">
        <Sparkles className="size-4" />
        {actionLabel}
      </Button>

      <div className="flex items-center gap-1">
        <Button variant="ghost" size="icon" aria-label="Ajustes">
          <Settings2 className="size-3.5" />
        </Button>
        <Button variant="ghost" size="icon" aria-label="Notificaciones">
          <Bell className="size-3.5" />
        </Button>
      </div>

      <div className="hidden min-w-0 items-center gap-2 border-l border-border pl-4 lg:flex">
        <div className="grid size-8 place-items-center rounded-full bg-accent text-xs font-semibold text-foreground-on-accent">
          A
        </div>
        <span className="max-w-40 truncate text-sm font-medium text-foreground">{label}</span>
      </div>
    </header>
  )
}
