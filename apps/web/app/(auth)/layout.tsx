export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 bg-surface-muted p-4">
      <span className="text-xl font-semibold tracking-tight text-foreground">Auyan</span>
      {children}
    </div>
  )
}
