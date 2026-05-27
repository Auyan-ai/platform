import { Bell, Search, Settings2, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface AppTopbarProps {
  actionLabel?: string
}

export function AppTopbar({ actionLabel = 'Acción rápida' }: AppTopbarProps) {
  return (
    <header className="flex h-14 items-center gap-4 border-b border-border bg-surface px-6">
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
    </header>
  )
}
