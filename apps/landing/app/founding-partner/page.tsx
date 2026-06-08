import { PageShell } from '@/components/SiteShell'
import { createPageMetadata } from '@/lib/metadata'
import { siteConfig } from '@/lib/site'
import Link from 'next/link'
import {
  ArrowRight,
  CheckCircle2,
  Clock3,
  FileCheck2,
  MessageSquareText,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'

export const metadata = createPageMetadata({
  title: 'Founding Partner Auyan',
  description:
    'Programa para los primeros clientes de Auyan: killer test en 24h, setup gratis, mes 1 gratis y operación gestionada para CX Shopify.',
  path: '/founding-partner',
})

const founderEmail = siteConfig.founderEmail

const offer = [
  ['Setup gratis', 'Auditoría inicial, AOPs base, KB curada y conexión al stack existente.'],
  ['Mes 1 gratis', 'Validamos el killer test y shadow mode antes de cobrar operación recurrente.'],
  ['Meses 2-6 a €690/mes', '50% off del plan Starter para los primeros cinco clientes.'],
  ['Sin permanencia', 'Si no vemos aprendizaje real, no te atrapamos en un contrato largo.'],
] as const

const process = [
  ['24h', 'Killer test', 'Nos mandas tres emails reales anonimizados y devolvemos respuestas comparables.'],
  ['Semana 1', 'Discovery operativo', 'Leemos políticas, conversaciones, tono de marca y restricciones Shopify.'],
  ['Semanas 2-4', 'Shadow mode', 'Auyan propone drafts internos mientras tu equipo conserva el control.'],
  ['Mes 2+', 'Activación gradual', 'Encendemos categorías cuando hay evidencia y límites claros.'],
] as const

const fit = [
  'Shopify como plataforma principal.',
  'Gorgias, Zendesk, Chatwoot Cloud o Intercom como helpdesk.',
  '500-1.000 tickets/mes o dolor claro de soporte repetitivo.',
  'Al menos una persona responsable de CX.',
  'Disponibilidad para feedback semanal durante las primeras 6 semanas.',
] as const

export default function FoundingPartnerPage() {
  return (
    <PageShell>
      <section className="relative overflow-hidden border-b border-border bg-background">
        <div className="absolute inset-0 bg-[linear-gradient(to_right,rgba(231,229,228,0.52)_1px,transparent_1px),linear-gradient(to_bottom,rgba(231,229,228,0.52)_1px,transparent_1px)] bg-[size:72px_72px] [mask-image:linear-gradient(to_bottom,black,transparent_82%)]" />
        <div className="relative mx-auto grid max-w-7xl gap-12 px-5 pb-20 pt-28 lg:grid-cols-[0.92fr_1.08fr] lg:items-center lg:pt-36">
          <div>
            <p className="inline-flex rounded-full border border-border bg-surface px-3 py-1 text-sm font-medium text-accent-foreground">
              Founding Partner
            </p>
            <h1 className="mt-6 max-w-3xl text-4xl font-semibold leading-[1.04] text-foreground sm:text-5xl md:text-7xl md:leading-[1.01]">
              Probemos Auyan con tus tickets reales.
            </h1>
            <p className="mt-6 max-w-2xl text-lg leading-8 text-foreground-body">
              El inicio no es una demo bonita. Es un killer test: tres emails anonimizados del
              último mes, respuestas de Auyan en 24h y una comparación honesta contra la respuesta
              real de tu equipo.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <a
                href={`mailto:${founderEmail}?subject=Killer%20test%20Auyan`}
                className="inline-flex h-11 items-center gap-2 rounded-full bg-accent px-5 text-sm font-medium text-foreground-on-accent transition-colors hover:bg-accent-hover"
              >
                Enviar emails anonimizados
                <ArrowRight className="size-4" />
              </a>
              <Link
                href="/pricing"
                className="inline-flex h-11 items-center rounded-full border border-border bg-surface px-5 text-sm font-medium text-foreground transition-colors hover:border-border-strong hover:bg-surface-muted"
              >
                Ver pricing completo
              </Link>
            </div>
          </div>

          <div className="rounded-2xl border border-neutral-800 bg-neutral-950 p-5 text-white shadow-[0_34px_110px_rgba(15,23,42,0.22)]">
            <div className="flex items-center justify-between border-b border-white/10 pb-4">
              <div>
                <p className="text-sm text-neutral-400">Programa inicial</p>
                <p className="mt-1 text-2xl font-semibold">5 cupos</p>
              </div>
              <span className="rounded-full border border-emerald-400/25 bg-emerald-400/10 px-3 py-1 text-sm font-medium text-emerald-200">
                Mes 1 gratis
              </span>
            </div>
            <div className="mt-5 grid gap-3">
              {offer.map(([title, body]) => (
                <div key={title} className="rounded-xl border border-white/10 bg-white/[0.055] p-4">
                  <div className="flex gap-3">
                    <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-emerald-300" />
                    <div>
                      <p className="font-semibold text-white">{title}</p>
                      <p className="mt-1 text-sm leading-6 text-neutral-300">{body}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="bg-surface py-20">
        <div className="mx-auto max-w-7xl px-5">
          <div className="max-w-3xl">
            <p className="text-sm font-medium text-accent-foreground">Proceso</p>
            <h2 className="mt-4 text-3xl font-semibold leading-tight text-foreground md:text-5xl">
              De tres emails a una categoría lista para shadow mode.
            </h2>
          </div>
          <div className="mt-10 grid gap-4 md:grid-cols-4">
            {process.map(([time, title, body]) => (
              <div key={title} className="rounded-xl border border-border bg-background p-5">
                <p className="text-sm font-semibold text-accent-foreground">{time}</p>
                <h3 className="mt-4 text-xl font-semibold text-foreground">{title}</h3>
                <p className="mt-3 text-sm leading-6 text-foreground-body">{body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="border-y border-border bg-background py-20">
        <div className="mx-auto grid max-w-7xl gap-8 px-5 lg:grid-cols-[0.85fr_1.15fr]">
          <div>
            <p className="text-sm font-medium text-accent-foreground">Buen fit</p>
            <h2 className="mt-4 text-3xl font-semibold leading-tight text-foreground md:text-5xl">
              Esto funciona mejor si ya existe una operación CX real.
            </h2>
            <p className="mt-4 text-lg leading-8 text-foreground-body">
              No buscamos volumen por volumen. Buscamos cinco marcas donde podamos demostrar valor
              rápido y construir un caso de estudio limpio.
            </p>
          </div>
          <div className="grid gap-3">
            {fit.map((item) => (
              <div key={item} className="flex gap-3 rounded-xl border border-border bg-surface p-4">
                <ShieldCheck className="mt-0.5 size-5 shrink-0 text-accent-foreground" />
                <p className="text-sm leading-6 text-foreground-body">{item}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="bg-surface py-20">
        <div className="mx-auto grid max-w-7xl gap-8 px-5 md:grid-cols-3">
          {[
            ['Killer test en 24h', Clock3, 'Comparación concreta antes de venderte un rollout.'],
            ['Feedback semanal', MessageSquareText, '30 minutos para revisar calidad, objeciones y categorías.'],
            ['Caso de estudio', FileCheck2, 'Solo cuando existan resultados que ambas partes quieran publicar.'],
          ].map(([title, Icon, body]) => (
            <div key={title as string} className="rounded-xl border border-border bg-background p-6">
              <Icon className="size-6 text-accent-foreground" />
              <h3 className="mt-5 text-xl font-semibold text-foreground">{title as string}</h3>
              <p className="mt-3 text-sm leading-6 text-foreground-body">{body as string}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="bg-foreground py-16 text-foreground-on-accent">
        <div className="mx-auto flex max-w-7xl flex-col gap-6 px-5 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="flex items-center gap-2 text-sm font-medium text-cobalt-200">
              <Sparkles className="size-4" />
              Auyan Founding Partner
            </p>
            <h2 className="mt-3 text-3xl font-semibold leading-tight md:text-5xl">
              Si el test no convence, no seguimos.
            </h2>
          </div>
          <a
            href={`mailto:${founderEmail}?subject=Founding%20Partner%20Auyan`}
            className="inline-flex h-11 shrink-0 items-center justify-center gap-2 rounded-full bg-surface px-5 text-sm font-medium transition-colors hover:bg-surface-muted"
            style={{ color: 'var(--color-neutral-900)' }}
          >
            Empezar
            <ArrowRight className="size-4" />
          </a>
        </div>
      </section>
    </PageShell>
  )
}
