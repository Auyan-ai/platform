import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Auyan',
  description: 'Dashboard de operaciones Auyan',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es" suppressHydrationWarning>
      <body className="bg-background text-foreground antialiased">{children}</body>
    </html>
  )
}
