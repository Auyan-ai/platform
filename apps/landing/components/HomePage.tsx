'use client'

import { motion } from 'framer-motion'
import {
  ArrowRight,
  BarChart3,
  CheckCircle2,
  ClipboardCheck,
  FileBarChart2,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'
import Link from 'next/link'
import { PageShell } from './SiteShell'

const outcomes = [
  ['60-70%', 'menos tickets que tocan humanos'],
  ['47s', 'first response objetivo'],
  ['cada lunes', 'reporte con propuestas'],
]

const workflow = [
  ['Conecta helpdesk', 'Gorgias, Zendesk o Chatwoot Cloud; Auyan hereda tus canales.'],
  ['Opera en shadow', 'La IA propone drafts y Auyan aprende de las correcciones.'],
  ['Activa por categoría', 'Auyan decide ramp-up cuando métricas y evals están listas.'],
  ['Mejora semanal', 'Reportes, KB drops y proposals alimentan el ciclo operativo.'],
]

const modules = [
  ['Reportes proactivos', FileBarChart2],
  ['KB curada', ClipboardCheck],
  ['Review Queue', CheckCircle2],
  ['Insights CX', BarChart3],
]

function ProductScene() {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
      <div className="absolute left-[38%] top-24 hidden w-[760px] rounded-lg border border-border bg-surface/92 p-4 shadow-[0_24px_80px_rgba(37,99,235,0.16)] lg:block">
        <div className="mb-4 flex items-center justify-between border-b border-border-subtle pb-3">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.14em] text-foreground-muted">
              Review Queue
            </p>
            <p className="mt-1 text-lg font-semibold text-foreground">Lunaria</p>
          </div>
          <span className="rounded-sm bg-warning-subtle px-2 py-1 text-xs font-medium text-warning-foreground">
            14 pendientes
          </span>
        </div>
        <div className="grid grid-cols-4 gap-3">
          {modules.map(([label, Icon], index) => (
            <motion.div
              key={label as string}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.12 * index, duration: 0.5 }}
              className="rounded-md border border-border-subtle bg-surface-muted p-3"
            >
              <Icon className="size-4 text-accent-foreground" />
              <p className="mt-5 text-xs font-medium text-foreground">{label as string}</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums text-foreground">
                {[4, 2, 6, 9][index]}
              </p>
            </motion.div>
          ))}
        </div>
        <div className="mt-4 rounded-md border border-border-subtle bg-surface p-4">
          <p className="text-sm font-semibold text-foreground">Auyan Weekly Report</p>
          <p className="mt-2 text-sm leading-6 text-foreground-body">
            Cambios de talla generó 18% más escalaciones. Propuesta: actualizar AOP size-exchange y
            añadir tres facts verificados.
          </p>
        </div>
      </div>
    </div>
  )
}

export function HomePage() {
  return (
    <PageShell>
      <section className="relative min-h-[92vh] overflow-hidden border-b border-border bg-background">
        <ProductScene />
        <div className="relative mx-auto flex max-w-7xl flex-col px-5 pb-20 pt-32">
          <div className="max-w-2xl">
            <p className="text-sm font-medium uppercase tracking-[0.18em] text-accent-foreground">
              Managed AI para CX e-commerce
            </p>
            <h1 className="mt-5 text-5xl font-semibold tracking-tight text-foreground md:text-7xl">
              Auyan
            </h1>
            <p className="mt-6 max-w-xl text-lg leading-8 text-foreground-body">
              Configuramos, mantenemos y optimizamos tu agente IA. Tu equipo CX conserva los casos
              complejos; Auyan se encarga de que lo repetitivo mejore cada semana.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link
                href="/founding-partner"
                className="inline-flex h-11 items-center gap-2 rounded-sm bg-accent px-5 text-sm font-medium text-foreground-on-accent transition-colors hover:bg-accent-hover"
              >
                Programa Founding Partner
                <ArrowRight className="size-4" />
              </Link>
              <Link
                href="/pricing"
                className="inline-flex h-11 items-center rounded-sm border border-border bg-surface px-5 text-sm font-medium text-foreground transition-colors hover:bg-surface-muted"
              >
                Ver pricing
              </Link>
            </div>
          </div>
          <div className="mt-16 grid max-w-3xl gap-3 md:grid-cols-3">
            {outcomes.map(([value, label]) => (
              <div key={value} className="rounded-md border border-border bg-surface/88 p-4">
                <p className="text-2xl font-semibold text-foreground">{value}</p>
                <p className="mt-1 text-sm text-foreground-muted">{label}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="bg-surface py-20">
        <div className="mx-auto max-w-7xl px-5">
          <div className="max-w-2xl">
            <h2 className="text-3xl font-semibold tracking-tight text-foreground md:text-5xl">
              Operación experta, no otro panel que configurar.
            </h2>
            <p className="mt-4 text-lg leading-8 text-foreground-body">
              Auyan trabaja sobre tu helpdesk, tu Shopify y tus políticas. Cada semana revisamos
              datos, aprobaciones, knowledge base y proposals para subir resolución sin romper la
              voz de marca.
            </p>
          </div>
          <div className="mt-10 grid gap-4 md:grid-cols-4">
            {workflow.map(([title, body], index) => (
              <motion.div
                key={title}
                initial={{ opacity: 0, y: 12 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: '-80px' }}
                transition={{ delay: index * 0.08, duration: 0.45 }}
                className="rounded-md border border-border bg-background p-5"
              >
                <span className="text-sm font-semibold text-accent-foreground">0{index + 1}</span>
                <h3 className="mt-6 text-lg font-semibold text-foreground">{title}</h3>
                <p className="mt-3 text-sm leading-6 text-foreground-body">{body}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      <section className="border-y border-border bg-background py-20">
        <div className="mx-auto grid max-w-7xl gap-8 px-5 lg:grid-cols-[0.9fr_1.1fr]">
          <div>
            <Sparkles className="size-8 text-accent-foreground" />
            <h2 className="mt-5 text-3xl font-semibold tracking-tight text-foreground md:text-5xl">
              El killer test
            </h2>
            <p className="mt-4 text-lg leading-8 text-foreground-body">
              Mándanos tres emails reales de clientes del último mes, anonimizados. En 24h te
              devolvemos el copy exacto que generaría Auyan para comparar contra tu respuesta real.
            </p>
          </div>
          <div className="rounded-lg border border-border bg-surface p-6">
            <div className="flex items-center gap-2 text-sm font-medium text-success-foreground">
              <ShieldCheck className="size-4" />
              Sin permanencia para Founding Partners
            </div>
            <div className="mt-6 grid gap-3">
              {[
                'Setup gratis',
                'Mes 1 gratis',
                'Mes 2-6 a €690/mes',
                'Caso de estudio público',
              ].map((item) => (
                <div key={item} className="flex items-center gap-3 text-foreground-body">
                  <CheckCircle2 className="size-4 text-success-foreground" />
                  <span>{item}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>
    </PageShell>
  )
}
