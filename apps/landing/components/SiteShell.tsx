import { ArrowRight } from 'lucide-react'
import Link from 'next/link'
import type { ReactNode } from 'react'

const navItems = [
  ['Pricing', '/pricing'],
  ['Founding Partner', '/founding-partner'],
  ['Security', '/security'],
  ['About', '/about'],
  ['Blog', '/blog'],
] as const

export function SiteHeader() {
  return (
    <header className="fixed left-0 right-0 top-0 z-50 border-b border-border/80 bg-background/85 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-5">
        <Link href="/" className="text-sm font-semibold tracking-tight">
          Auyan
        </Link>
        <nav className="hidden items-center gap-6 text-sm text-foreground-muted md:flex">
          {navItems.map(([label, href]) => (
            <Link key={href} href={href} className="transition-colors hover:text-foreground">
              {label}
            </Link>
          ))}
        </nav>
        <Link
          href="/founding-partner"
          className="inline-flex h-9 items-center gap-2 rounded-sm bg-accent px-3 text-sm font-medium text-foreground-on-accent transition-colors hover:bg-accent-hover"
        >
          Ver programa
          <ArrowRight className="size-4" />
        </Link>
      </div>
    </header>
  )
}

export function SiteFooter() {
  return (
    <footer className="border-t border-border bg-surface">
      <div className="mx-auto flex max-w-7xl flex-col gap-4 px-5 py-8 text-sm text-foreground-muted md:flex-row md:items-center md:justify-between">
        <p>Auyan opera agentes IA para CX e-commerce.</p>
        <div className="flex flex-wrap gap-4">
          {navItems.map(([label, href]) => (
            <Link key={href} href={href} className="hover:text-foreground">
              {label}
            </Link>
          ))}
        </div>
      </div>
    </footer>
  )
}

export function PageShell({ children }: { children: ReactNode }) {
  return (
    <>
      <SiteHeader />
      <main>{children}</main>
      <SiteFooter />
    </>
  )
}

export function SimplePage({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string
  title: string
  children: ReactNode
}) {
  return (
    <PageShell>
      <section className="mx-auto min-h-[78vh] max-w-4xl px-5 pb-20 pt-32">
        <p className="text-sm font-medium uppercase tracking-[0.18em] text-accent-foreground">
          {eyebrow}
        </p>
        <h1 className="mt-4 text-4xl font-semibold tracking-tight text-foreground md:text-6xl">
          {title}
        </h1>
        <div className="mt-8 space-y-6 text-lg leading-8 text-foreground-body">{children}</div>
      </section>
    </PageShell>
  )
}
