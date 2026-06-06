import { PageShell } from '@/components/SiteShell'
import type { Metadata } from 'next'
import Link from 'next/link'
import {
  ArrowRight,
  BarChart3,
  CheckCircle2,
  FileBarChart2,
  Gauge,
  ShieldCheck,
} from 'lucide-react'

export const metadata: Metadata = {
  title: 'Pricing Auyan',
  description:
    'Planes de Auyan para Managed AI en CX e-commerce: Founding Partner, Starter, Growth y Scale ligados a operación y volumen de tickets.',
}

const tiers = [
  {
    name: 'Starter',
    setup: 'Gratis',
    price: '€890',
    tickets: '1.000 tickets/mes',
    fit: '2-4 personas CX, 500-1.000 tickets/mes.',
    note: 'Entrada natural después del programa Founding Partner.',
    featured: false,
  },
  {
    name: 'Growth',
    setup: '€1.500',
    price: '€2.490',
    tickets: '3.000 tickets/mes',
    fit: '4-10 personas CX, 1.500-3.000 tickets/mes.',
    note: 'Target principal para marcas con soporte repetitivo ya visible.',
    featured: true,
  },
  {
    name: 'Scale',
    setup: '€4.000',
    price: '€5.990',
    tickets: '10.000 tickets/mes',
    fit: '10-25 personas CX, 3.000-10.000 tickets/mes.',
    note: 'Para operaciones con más categorías, permisos y reporting.',
    featured: false,
  },
] as const

const included = [
  'Agente IA operado por Auyan.',
  'AOPs, KB curada y permisos por intención.',
  'Shadow mode antes de activar categorías.',
  'Review Queue para acciones L3.',
  'Reporte semanal con propuestas accionables.',
  'Mejora continua sobre conversaciones reales.',
] as const

const faqs = [
  [
    '¿Cobran por asiento?',
    'No. El pricing está ligado a operación y volumen de tickets, no a cuántas personas entran al dashboard.',
  ],
  [
    '¿Qué pasa si supero el volumen incluido?',
    'Los tickets extra se calculan como overage. El rango objetivo es €0,15-€0,30 por ticket extra según tier y uso real.',
  ],
  [
    '¿El setup incluye migrar todo mi soporte?',
    'No migramos tu helpdesk. Auyan se conecta al stack existente y prepara las categorías que tienen sentido activar primero.',
  ],
  [
    '¿Estos precios son definitivos?',
    'Son precios provisionales para la primera etapa comercial. Los ajustaremos con datos reales de volumen, coste LLM y horas humanas.',
  ],
] as const

export default function PricingPage() {
  return (
    <PageShell>
      <section className="relative overflow-hidden border-b border-border bg-background">
        <div className="absolute inset-0 bg-[linear-gradient(to_right,rgba(231,229,228,0.52)_1px,transparent_1px),linear-gradient(to_bottom,rgba(231,229,228,0.52)_1px,transparent_1px)] bg-[size:72px_72px] [mask-image:linear-gradient(to_bottom,black,transparent_82%)]" />
        <div className="relative mx-auto max-w-7xl px-5 pb-16 pt-28 lg:pt-36">
          <div className="max-w-4xl">
            <p className="inline-flex rounded-full border border-border bg-surface px-3 py-1 text-sm font-medium text-accent-foreground">
              Pricing
            </p>
            <h1 className="mt-6 text-4xl font-semibold leading-[1.04] text-foreground sm:text-5xl md:text-7xl md:leading-[1.01]">
              Planes ligados a operación, no asientos.
            </h1>
            <p className="mt-6 max-w-2xl text-lg leading-8 text-foreground-body">
              Auyan no vende otro panel que configurar. Vendemos una operación gestionada: agente
              IA, guardrails, mejoras semanales y control humano donde importa.
            </p>
          </div>

          <div className="mt-10 rounded-2xl border border-neutral-800 bg-neutral-950 p-5 text-white md:flex md:items-center md:justify-between">
            <div>
              <p className="text-sm font-medium text-cobalt-200">Founding Partner</p>
              <h2 className="mt-2 text-2xl font-semibold">Primeros cinco clientes</h2>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-neutral-300">
                Setup gratis, mes 1 gratis, meses 2-6 a €690/mes y sin permanencia. Empezamos con
                tres emails anonimizados y un killer test en 24h.
              </p>
            </div>
            <Link
              href="/founding-partner"
              className="mt-5 inline-flex h-11 items-center gap-2 rounded-full bg-surface px-5 text-sm font-medium transition-colors hover:bg-surface-muted md:mt-0"
              style={{ color: 'var(--color-neutral-900)' }}
            >
              Ver programa
              <ArrowRight className="size-4" />
            </Link>
          </div>
        </div>
      </section>

      <section className="bg-surface py-20">
        <div className="mx-auto max-w-7xl px-5">
          <div className="grid gap-4 lg:grid-cols-3">
            {tiers.map((tier) => (
              <div
                key={tier.name}
                className={`rounded-2xl border p-6 ${
                  tier.featured
                    ? 'border-accent bg-accent-subtle shadow-[0_18px_70px_rgba(37,99,235,0.12)]'
                    : 'border-border bg-background'
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-xl font-semibold text-foreground">{tier.name}</p>
                    <p className="mt-2 text-sm leading-6 text-foreground-muted">{tier.fit}</p>
                  </div>
                  {tier.featured && (
                    <span className="rounded-full bg-accent px-3 py-1 text-xs font-medium text-foreground-on-accent">
                      Target
                    </span>
                  )}
                </div>
                <div className="mt-8">
                  <p className="text-sm font-medium text-foreground-muted">Setup</p>
                  <p className="mt-1 text-2xl font-semibold text-foreground">{tier.setup}</p>
                  <p className="mt-6 text-sm font-medium text-foreground-muted">Operación mensual</p>
                  <p className="mt-1 text-4xl font-semibold text-foreground">
                    {tier.price}
                    <span className="text-base font-medium text-foreground-muted">/mes</span>
                  </p>
                  <p className="mt-5 text-sm font-semibold text-accent-foreground">{tier.tickets}</p>
                  <p className="mt-3 text-sm leading-6 text-foreground-body">{tier.note}</p>
                </div>
              </div>
            ))}
          </div>

          <div className="mt-10 grid gap-8 rounded-2xl border border-border bg-background p-6 lg:grid-cols-[0.78fr_1.22fr]">
            <div>
              <p className="text-sm font-medium text-accent-foreground">Incluido</p>
              <h2 className="mt-4 text-3xl font-semibold leading-tight text-foreground">
                Lo que justifica el fee no es la IA. Es la operación.
              </h2>
              <p className="mt-4 text-sm leading-6 text-foreground-body">
                El reporte semanal y la mejora gestionada son parte central del producto, no un
                add-on.
              </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              {included.map((item) => (
                <div key={item} className="flex gap-3 rounded-xl border border-border bg-surface p-4">
                  <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-success-foreground" />
                  <p className="text-sm leading-6 text-foreground-body">{item}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="border-y border-border bg-background py-20">
        <div className="mx-auto grid max-w-7xl gap-6 px-5 md:grid-cols-3">
          {[
            ['Overage controlado', Gauge, 'Tickets extra en rango €0,15-€0,30 según tier y consumo real.'],
            ['Créditos por performance', BarChart3, 'Objetivos de resolución se revisan por etapa, no en el día uno.'],
            ['Acciones sensibles protegidas', ShieldCheck, 'Reembolsos, cambios y decisiones L3 pasan por aprobación.'],
          ].map(([title, Icon, body]) => (
            <div key={title as string} className="rounded-xl border border-border bg-surface p-6">
              <Icon className="size-6 text-accent-foreground" />
              <h3 className="mt-5 text-xl font-semibold text-foreground">{title as string}</h3>
              <p className="mt-3 text-sm leading-6 text-foreground-body">{body as string}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="bg-surface py-20">
        <div className="mx-auto grid max-w-7xl gap-8 px-5 lg:grid-cols-[0.8fr_1.2fr]">
          <div>
            <p className="text-sm font-medium text-accent-foreground">FAQ</p>
            <h2 className="mt-4 text-3xl font-semibold leading-tight text-foreground md:text-5xl">
              Preguntas que conviene aclarar antes de comprar.
            </h2>
          </div>
          <div className="grid gap-3">
            {faqs.map(([question, answer]) => (
              <div key={question} className="rounded-xl border border-border bg-background p-5">
                <div className="flex gap-3">
                  <FileBarChart2 className="mt-1 size-5 shrink-0 text-accent-foreground" />
                  <div>
                    <h3 className="font-semibold text-foreground">{question}</h3>
                    <p className="mt-2 text-sm leading-6 text-foreground-body">{answer}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </PageShell>
  )
}
