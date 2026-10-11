import { Card } from '@/components/ui/card'

interface AuthCardProps {
  title: string
  description?: React.ReactNode
  children: React.ReactNode
}

/** Tarjeta común de las pantallas de auth (login, revisa tu correo, fijar contraseña). */
export function AuthCard({ title, description, children }: AuthCardProps) {
  return (
    <Card className="w-full max-w-sm p-8">
      <div className="mb-6 text-center">
        <h1 className="text-lg font-semibold text-foreground">{title}</h1>
        {description && <p className="mt-1 text-sm text-foreground-muted">{description}</p>}
      </div>
      {children}
    </Card>
  )
}

export function AuthError({ children }: { children: React.ReactNode }) {
  return (
    <div
      role="alert"
      className="rounded-sm bg-danger-subtle px-3 py-2 text-sm text-danger-foreground"
    >
      {children}
    </div>
  )
}
