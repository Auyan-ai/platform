'use client'

import { motion } from 'framer-motion'
import {
  ArrowRight,
  BarChart3,
  Bot,
  Check,
  CheckCircle2,
  ClipboardCheck,
  Clock3,
  FileBarChart2,
  Gauge,
  LockKeyhole,
  MessageSquareText,
  SearchCheck,
  ShieldCheck,
  ShoppingBag,
  Sparkles,
  Users,
} from 'lucide-react'
import Link from 'next/link'
import { PageShell } from './SiteShell'

const outcomes = [
  ['60-70%', 'menos carga repetitiva'],
  ['47s', 'first response objetivo'],
  ['24h', 'killer test con emails reales'],
] as const

const stackSignals = ['Shopify', 'Gorgias', 'Zendesk', 'Chatwoot Cloud', 'Intercom reactivo']

const proofSignals = [
  ['Shopify-first', 'Pedidos, clientes, productos y acciones con aprobación.'],
  ['Human-approved', 'L3 y cambios sensibles pasan por criterio humano.'],
  ['Managed weekly', 'AOPs, KB y reportes mejoran con tickets reales.'],
] as const

const reliabilityPillars = [
  {
    title: 'Evaluación antes de activar',
    body: 'Shadow mode compara drafts contra respuestas reales antes de poner una categoría en producción.',
    icon: SearchCheck,
  },
  {
    title: 'Guardrails por intención',
    body: 'Cada acción tiene permisos, umbrales y fallback humano para proteger marca, margen y experiencia.',
    icon: ShieldCheck,
  },
  {
    title: 'Optimización gestionada',
    body: 'Cada semana convertimos conversaciones en mejoras de AOPs, knowledge base y automatización.',
    icon: Gauge,
  },
] as const

const bentoItems = [
  {
    title: 'Operación gestionada',
    body: 'Auyan configura, prueba y mejora el agente cada semana. El cliente no aprende prompts ni mantiene reglas.',
    icon: ClipboardCheck,
    className: 'lg:col-span-2 lg:row-span-2',
    visual: 'report',
  },
  {
    title: 'Acciones Shopify',
    body: 'Consulta pedidos, productos y clientes. Ejecuta cambios sensibles solo con aprobación.',
    icon: ShoppingBag,
    className: 'lg:col-span-1',
    visual: 'skills',
  },
  {
    title: 'Control humano',
    body: 'Tu equipo conserva criterio, escalados y casos complejos.',
    icon: Users,
    className: 'lg:col-span-1',
    visual: 'approval',
  },
  {
    title: 'Insights que se vuelven mejoras',
    body: 'Cada semana, tickets reales alimentan propuestas de KB, AOPs y activación por categoría.',
    icon: BarChart3,
    className: 'lg:col-span-2',
    visual: 'insights',
  },
] as const

const workflow = [
  ['Discovery', 'Leemos políticas, conversaciones reales y tono de marca.'],
  ['Build', 'Creamos AOPs, KB curada y permisos por tipo de acción.'],
  ['Shadow mode', 'La IA propone drafts como nota interna, tu equipo responde.'],
  ['Activación gradual', 'Se activa por categoría cuando hay confianza operativa.'],
] as const

const faqs = [
  [
    '¿Auyan reemplaza a mi equipo de soporte?',
    'No. Auyan quita carga repetitiva para que tu equipo se quede con los casos donde hace falta criterio, empatía y contexto comercial.',
  ],
  [
    '¿Tengo que cambiar de helpdesk?',
    'No. Auyan se conecta a Gorgias, Zendesk o Chatwoot Cloud y hereda los canales que ya usa tu equipo.',
  ],
  [
    '¿Qué pasa con acciones sensibles como reembolsos o cambios de dirección?',
    'Las acciones L3 pasan por aprobación humana. La IA no ejecuta cambios destructivos sin permiso.',
  ],
  [
    '¿Por qué no usar un chatbot self-serve?',
    'Porque el valor no es solo responder. El valor está en operar, auditar, corregir y mejorar el sistema con datos reales cada semana.',
  ],
] as const

function Reveal({
  children,
  delay = 0,
  className,
}: {
  children: React.ReactNode
  delay?: number
  className?: string
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '-80px' }}
      transition={{ duration: 0.5, delay, ease: [0.2, 0.8, 0.2, 1] }}
      className={className}
    >
      {children}
    </motion.div>
  )
}

function HeroBackground() {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
      <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(255,255,255,0)_0%,rgba(239,244,255,0.62)_52%,rgba(250,250,249,1)_100%)]" />
      <div className="absolute inset-0 bg-[linear-gradient(to_right,rgba(231,229,228,0.52)_1px,transparent_1px),linear-gradient(to_bottom,rgba(231,229,228,0.52)_1px,transparent_1px)] bg-[size:72px_72px] [mask-image:linear-gradient(to_bottom,black,transparent_82%)]" />
      <motion.div
        className="absolute left-[8%] top-28 h-px w-[84%] bg-[linear-gradient(90deg,transparent,rgba(37,99,235,0.44),transparent)]"
        animate={{ opacity: [0.2, 0.82, 0.2], x: [-24, 24, -24] }}
        transition={{ duration: 7, repeat: Number.POSITIVE_INFINITY, ease: 'easeInOut' }}
      />
      <motion.div
        className="absolute right-[18%] top-44 h-[360px] w-px bg-[linear-gradient(180deg,transparent,rgba(37,99,235,0.28),transparent)]"
        animate={{ opacity: [0.16, 0.7, 0.16], y: [-18, 18, -18] }}
        transition={{ duration: 8, repeat: Number.POSITIVE_INFINITY, ease: 'easeInOut' }}
      />
    </div>
  )
}

function HeroScene() {
  return (
    <div
      className="relative mx-auto w-full min-w-0 max-w-[640px] lg:max-w-none"
      aria-label="Vista resumida del sistema operativo de agentes Auyan"
    >
      <div className="absolute -inset-6 rounded-[2rem] bg-[radial-gradient(circle_at_30%_20%,rgba(37,99,235,0.18),transparent_34%),radial-gradient(circle_at_80%_70%,rgba(20,184,166,0.14),transparent_32%)] blur-2xl" />
      <div className="relative overflow-hidden rounded-2xl border border-neutral-800 bg-neutral-950 p-3 shadow-[0_34px_110px_rgba(15,23,42,0.22)]">
        <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(to_right,rgba(255,255,255,0.055)_1px,transparent_1px),linear-gradient(to_bottom,rgba(255,255,255,0.055)_1px,transparent_1px)] bg-[size:42px_42px] [mask-image:linear-gradient(to_bottom,black,transparent_88%)]" />
        <div className="relative flex items-center justify-between border-b border-white/10 px-2 pb-3">
          <div>
            <p className="text-xs font-medium text-neutral-400">Auyan Agent OS</p>
            <p className="mt-1 text-lg font-semibold text-white">Marea Studio</p>
          </div>
          <span className="hidden rounded-full border border-emerald-400/25 bg-emerald-400/10 px-3 py-1 text-xs font-medium text-emerald-200 sm:inline-flex">
            Live shadow mode
          </span>
        </div>

        <div className="relative grid min-w-0 gap-3 pt-3 lg:grid-cols-[0.95fr_1.05fr]">
          <div className="min-w-0 space-y-3">
            {[
              ['Cambio de dirección', 'Approval L3 antes de tocar Shopify', 'pending'],
              ['Consulta de envío', 'Respuesta aprobada por política', 'success'],
              ['Devolución fuera de política', 'Escalado con contexto completo', 'danger'],
            ].map(([title, subtitle, state]) => (
              <div
                key={title}
                className="rounded-xl border border-white/10 bg-white/[0.045] p-3"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-white">{title}</p>
                    <p className="mt-1 text-xs text-neutral-400">{subtitle}</p>
                  </div>
                  <span
                    className={`mt-0.5 size-2.5 rounded-full ${
                      state === 'success'
                        ? 'bg-emerald-400'
                        : state === 'danger'
                          ? 'bg-rose-300'
                          : 'bg-amber-300'
                    }`}
                  />
                </div>
              </div>
            ))}
          </div>

          <div className="min-w-0 rounded-xl border border-white/10 bg-white/[0.07] p-4">
            <div className="flex items-center gap-2 text-sm font-semibold text-white">
              <Bot className="size-4 text-cobalt-200" />
              Agent decision trace
            </div>
            <p className="mt-3 break-words text-sm leading-6 text-neutral-300">
              Intención: cambio de talla. Confianza alta para draft, acción sensible bloqueada
              hasta aprobación humana.
            </p>
            <div className="mt-5 grid grid-cols-3 gap-2">
              {[
                ['94%', 'confidence'],
                ['L3', 'approval'],
                ['6', 'KB gaps'],
              ].map(([value, label]) => (
                <div key={label} className="rounded-lg bg-white/[0.08] p-3">
                  <p className="text-xl font-semibold text-white">{value}</p>
                  <p className="mt-1 text-[11px] leading-4 text-neutral-400">{label}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <motion.div
        className="absolute -bottom-5 left-5 hidden rounded-full border border-border bg-surface px-4 py-2 text-sm font-medium text-foreground shadow-[0_12px_34px_rgba(28,25,23,0.10)] md:flex"
        animate={{ y: [0, -6, 0] }}
        transition={{ duration: 4, repeat: Number.POSITIVE_INFINITY, ease: 'easeInOut' }}
      >
        Managed by Agent Engineers
      </motion.div>
    </div>
  )
}

function BentoVisual({ kind }: { kind: (typeof bentoItems)[number]['visual'] }) {
  if (kind === 'report') {
    return (
      <div className="mt-8 rounded-lg border border-border-subtle bg-background p-4">
        <div className="flex items-center justify-between gap-3">
          <span className="text-sm font-semibold text-foreground">Reporte semanal</span>
          <span className="rounded-full bg-accent-subtle px-2.5 py-1 text-xs font-medium text-accent-foreground">
            lunes
          </span>
        </div>
        <div className="mt-4 space-y-2">
          {['Top motivo: cambios de talla', 'Update propuesto: AOP size-exchange', 'Impacto esperado: menos escalados'].map(
            (item) => (
              <div key={item} className="flex items-center gap-2 text-sm text-foreground-body">
                <CheckCircle2 className="size-4 text-success-foreground" />
                <span>{item}</span>
              </div>
            ),
          )}
        </div>
      </div>
    )
  }

  if (kind === 'skills') {
    return (
      <div className="mt-8 grid grid-cols-2 gap-2">
        {['Pedidos', 'Productos', 'Dirección', 'Reembolso'].map((item, index) => (
          <span
            key={item}
            className={`rounded-md border px-3 py-2 text-xs font-medium ${
              index > 1
                ? 'border-warning-subtle bg-warning-subtle text-warning-foreground'
                : 'border-border-subtle bg-background text-foreground-body'
            }`}
          >
            {item}
          </span>
        ))}
      </div>
    )
  }

  if (kind === 'approval') {
    return (
      <div className="mt-8 rounded-lg border border-border-subtle bg-background p-4">
        <div className="flex items-center gap-2 text-sm font-medium text-foreground">
          <LockKeyhole className="size-4 text-accent-foreground" />
          Approval gate
        </div>
        <p className="mt-2 text-xs leading-5 text-foreground-muted">
          Acciones sensibles esperan confirmación antes de tocar Shopify.
        </p>
      </div>
    )
  }

  return (
    <div className="mt-8 flex items-end gap-2">
      {[36, 54, 42, 70, 58].map((height, index) => (
        <div key={height} className="flex-1 rounded-t-md bg-accent-subtle">
          <motion.div
            initial={{ height: 8 }}
            whileInView={{ height }}
            viewport={{ once: true }}
            transition={{ delay: index * 0.05, duration: 0.45 }}
            className="rounded-t-md bg-accent"
          />
        </div>
      ))}
    </div>
  )
}

export function HomePage() {
  return (
    <PageShell>
      <section className="relative overflow-hidden border-b border-border bg-background">
        <HeroBackground />
        <div className="relative mx-auto grid max-w-7xl gap-14 px-5 pb-16 pt-28 lg:grid-cols-[0.9fr_1.1fr] lg:items-center lg:pb-24 lg:pt-[8.5rem]">
          <div className="min-w-0">
            <p className="inline-flex rounded-full border border-border bg-surface/80 px-3 py-1 text-sm font-medium text-accent-foreground">
              Managed AI para Shopify CX
            </p>
            <h1 className="mt-6 max-w-3xl text-4xl font-semibold leading-[1.04] text-foreground sm:text-5xl md:text-7xl md:leading-[1.01]">
              AI agents for support that cannot feel automated.
            </h1>
            <p className="mt-6 max-w-2xl text-lg leading-8 text-foreground-body">
              Auyan opera agentes IA para marcas Shopify: resolvemos tickets repetitivos,
              bloqueamos acciones sensibles hasta aprobación humana y mejoramos el sistema cada
              semana con conversaciones reales.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link
                href="/founding-partner"
                className="inline-flex h-11 items-center gap-2 rounded-full bg-accent px-5 text-sm font-medium text-foreground-on-accent transition-colors hover:bg-accent-hover"
              >
                Probar el killer test
                <ArrowRight className="size-4" />
              </Link>
              <Link
                href="/#producto"
                className="inline-flex h-11 items-center rounded-full border border-border bg-surface px-5 text-sm font-medium text-foreground transition-colors hover:border-border-strong hover:bg-surface-muted"
              >
                Ver cómo funciona
              </Link>
            </div>

            <div className="mt-10 hidden max-w-2xl gap-3 sm:grid sm:grid-cols-3">
              {outcomes.map(([value, label]) => (
                <div key={value} className="rounded-xl border border-border bg-surface/88 p-4">
                  <p className="text-2xl font-semibold text-foreground">{value}</p>
                  <p className="mt-1 text-sm leading-5 text-foreground-muted">{label}</p>
                </div>
              ))}
            </div>
          </div>

          <HeroScene />
        </div>

        <div className="relative border-t border-border/70 bg-surface/82">
          <div className="mx-auto grid max-w-7xl gap-6 px-5 py-6 lg:grid-cols-[0.95fr_1.05fr] lg:items-center">
            <div>
              <p className="text-sm font-semibold text-foreground">
                Diseñado para operaciones CX que ya viven en ecommerce.
              </p>
              <div className="mt-3 flex flex-wrap gap-2 text-sm text-foreground-muted">
                {stackSignals.map((item) => (
                  <span key={item} className="rounded-full border border-border bg-background px-3 py-1">
                    {item}
                  </span>
                ))}
              </div>
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              {proofSignals.map(([title, body]) => (
                <div key={title} className="rounded-xl border border-border bg-background p-4">
                  <p className="text-sm font-semibold text-foreground">{title}</p>
                  <p className="mt-2 text-xs leading-5 text-foreground-muted">{body}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section id="producto" className="scroll-mt-20 bg-surface py-20">
        <div className="mx-auto max-w-7xl px-5">
          <Reveal className="max-w-3xl">
            <p className="text-sm font-medium text-accent-foreground">Producto</p>
            <h2 className="mt-4 text-3xl font-semibold leading-tight text-foreground md:text-5xl">
              Operación experta, no otro panel que configurar.
            </h2>
            <p className="mt-4 text-lg leading-8 text-foreground-body">
              Auyan combina agente IA, AOPs, approvals, knowledge base curada y reportes semanales
              para mejorar soporte sin soltar el control de CX.
            </p>
          </Reveal>

          <div className="mt-10 grid gap-4 lg:grid-cols-4">
            {bentoItems.map(({ title, body, icon: Icon, className, visual }, index) => (
              <Reveal
                key={title}
                delay={index * 0.05}
                className={`rounded-xl border border-border bg-background p-6 shadow-[0_0_2px_0_rgba(175,178,206,0.36),0_1px_4px_0_rgba(4,4,52,0.06)] ${className}`}
              >
                <div className="flex items-start gap-3">
                  <Icon className="mt-1 size-5 shrink-0 text-accent-foreground" />
                  <div>
                    <h3 className="text-lg font-semibold text-foreground">{title}</h3>
                    <p className="mt-2 text-sm leading-6 text-foreground-body">{body}</p>
                  </div>
                </div>
                <BentoVisual kind={visual} />
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section className="border-y border-border bg-neutral-950 py-20 text-white">
        <div className="mx-auto grid max-w-7xl gap-10 px-5 lg:grid-cols-[0.82fr_1.18fr] lg:items-start">
          <Reveal>
            <p className="text-sm font-medium text-cobalt-200">Reliability layer</p>
            <h2 className="mt-4 text-3xl font-semibold leading-tight md:text-5xl">
              La IA no se activa por fe. Se activa por evidencia.
            </h2>
            <p className="mt-5 text-lg leading-8 text-neutral-300">
              La promesa no es prender un chatbot. Es demostrar que cada respuesta, acción y
              escalado tiene criterio operativo detrás.
            </p>
          </Reveal>

          <div className="grid gap-3">
            {reliabilityPillars.map(({ title, body, icon: Icon }, index) => (
              <Reveal
                key={title}
                delay={index * 0.05}
                className="rounded-2xl border border-white/10 bg-white/[0.055] p-5"
              >
                <div className="flex gap-4">
                  <span className="grid size-10 shrink-0 place-items-center rounded-full bg-white text-neutral-950">
                    <Icon className="size-4" />
                  </span>
                  <div>
                    <h3 className="text-lg font-semibold text-white">{title}</h3>
                    <p className="mt-2 text-sm leading-6 text-neutral-300">{body}</p>
                  </div>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section id="como-funciona" className="scroll-mt-20 border-y border-border bg-background py-20">
        <div className="mx-auto max-w-7xl px-5">
          <Reveal className="grid gap-8 lg:grid-cols-[0.82fr_1.18fr] lg:items-start">
            <div>
              <p className="text-sm font-medium text-accent-foreground">Cómo funciona</p>
              <h2 className="mt-4 text-3xl font-semibold leading-tight text-foreground md:text-5xl">
                De conversaciones reales a categorías activas.
              </h2>
              <p className="mt-4 text-lg leading-8 text-foreground-body">
                No prendemos la IA de golpe. Primero aprende en shadow mode, luego se activa por
                categoría cuando el comportamiento está probado.
              </p>
            </div>
            <div className="relative grid gap-3">
              <div className="absolute bottom-8 left-5 top-8 hidden w-px bg-border md:block" />
              {workflow.map(([title, body], index) => (
                <motion.div
                  key={title}
                  initial={{ opacity: 0, x: 12 }}
                  whileInView={{ opacity: 1, x: 0 }}
                  viewport={{ once: true, margin: '-80px' }}
                  transition={{ delay: index * 0.07, duration: 0.45 }}
                  className="relative rounded-xl border border-border bg-surface p-5"
                >
                  <div className="flex gap-4">
                    <span className="relative z-10 grid size-10 shrink-0 place-items-center rounded-full bg-accent text-sm font-semibold text-foreground-on-accent">
                      {index + 1}
                    </span>
                    <div>
                      <h3 className="text-lg font-semibold text-foreground">{title}</h3>
                      <p className="mt-2 text-sm leading-6 text-foreground-body">{body}</p>
                    </div>
                  </div>
                </motion.div>
              ))}
            </div>
          </Reveal>
        </div>
      </section>

      <section className="bg-surface py-20">
        <div className="mx-auto grid max-w-7xl gap-8 px-5 lg:grid-cols-[0.9fr_1.1fr] lg:items-center">
          <Reveal>
            <Sparkles className="size-8 text-accent-foreground" />
            <h2 className="mt-5 text-3xl font-semibold leading-tight text-foreground md:text-5xl">
              El killer test
            </h2>
            <p className="mt-4 text-lg leading-8 text-foreground-body">
              Mándanos tres emails reales de clientes del último mes, anonimizados. En 24h te
              devolvemos el copy exacto que generaría Auyan para compararlo contra tu respuesta real.
            </p>
            <div className="mt-7 flex flex-wrap gap-3">
              <a
                href="mailto:founders@auyan.ai?subject=Killer%20test%20Auyan"
                className="inline-flex h-11 items-center gap-2 rounded-full bg-accent px-5 text-sm font-medium text-foreground-on-accent transition-colors hover:bg-accent-hover"
              >
                Enviar emails anonimizados
                <ArrowRight className="size-4" />
              </a>
              <Link
                href="/founding-partner"
                className="inline-flex h-11 items-center rounded-full border border-border bg-background px-5 text-sm font-medium text-foreground transition-colors hover:border-border-strong hover:bg-surface-muted"
              >
                Ver Founding Partner
              </Link>
            </div>
          </Reveal>

          <Reveal delay={0.08} className="rounded-xl border border-border bg-background p-6">
            <div className="flex items-center gap-2 text-sm font-medium text-success-foreground">
              <ShieldCheck className="size-4" />
              Sin permanencia para Founding Partners
            </div>
            <div className="mt-6 grid gap-3 sm:grid-cols-2">
              {[
                ['Setup gratis', Clock3],
                ['Mes 1 gratis', Check],
                ['Meses 2-6 a €690/mes', FileBarChart2],
                ['Caso de estudio público', SearchCheck],
              ].map(([item, Icon]) => (
                <div key={item as string} className="flex items-center gap-3 text-foreground-body">
                  <span className="grid size-8 shrink-0 place-items-center rounded-full bg-success-subtle text-success-foreground">
                    <Icon className="size-4" />
                  </span>
                  <span>{item as string}</span>
                </div>
              ))}
            </div>
          </Reveal>
        </div>
      </section>

      <section className="border-y border-border bg-background py-20">
        <div className="mx-auto max-w-7xl px-5">
          <Reveal className="grid gap-8 lg:grid-cols-[0.8fr_1.2fr]">
            <div>
              <p className="text-sm font-medium text-accent-foreground">Pricing</p>
              <h2 className="mt-4 text-3xl font-semibold leading-tight text-foreground md:text-5xl">
                Planes ligados a operación, no asientos.
              </h2>
              <p className="mt-4 text-lg leading-8 text-foreground-body">
                Primeros clientes entran por Founding Partner. Después, Starter y Growth cubren el
                rango donde Auyan tiene más ventaja operativa.
              </p>
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              {[
                ['Starter', '€890', '1.000 tickets/mes'],
                ['Growth', '€2.490', '3.000 tickets/mes'],
                ['Scale', '€5.990', '10.000 tickets/mes'],
              ].map(([name, price, tickets], index) => (
                <div
                  key={name}
                  className={`rounded-xl border p-5 ${
                    index === 1
                      ? 'border-accent bg-accent-subtle'
                      : 'border-border bg-surface'
                  }`}
                >
                  <p className="text-sm font-semibold text-foreground">{name}</p>
                  <p className="mt-5 text-3xl font-semibold text-foreground">{price}</p>
                  <p className="mt-1 text-sm text-foreground-muted">/mes</p>
                  <p className="mt-5 text-sm font-medium text-accent-foreground">{tickets}</p>
                </div>
              ))}
            </div>
          </Reveal>
        </div>
      </section>

      <section className="bg-surface py-20">
        <div className="mx-auto grid max-w-7xl gap-8 px-5 lg:grid-cols-[0.8fr_1.2fr]">
          <Reveal>
            <p className="text-sm font-medium text-accent-foreground">Preguntas frecuentes</p>
            <h2 className="mt-4 text-3xl font-semibold leading-tight text-foreground md:text-5xl">
              Lo que conviene aclarar antes de hablar.
            </h2>
          </Reveal>
          <div className="grid gap-3">
            {faqs.map(([question, answer], index) => (
              <Reveal
                key={question}
                delay={index * 0.04}
                className="rounded-xl border border-border bg-background p-5"
              >
                <div className="flex gap-3">
                  <MessageSquareText className="mt-1 size-5 shrink-0 text-accent-foreground" />
                  <div>
                    <h3 className="font-semibold text-foreground">{question}</h3>
                    <p className="mt-2 text-sm leading-6 text-foreground-body">{answer}</p>
                  </div>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section className="bg-foreground py-16 text-foreground-on-accent">
        <div className="mx-auto flex max-w-7xl flex-col gap-6 px-5 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-sm font-medium text-cobalt-200">Auyan Founding Partner</p>
            <h2 className="mt-3 text-3xl font-semibold leading-tight md:text-5xl">
              Si tu soporte ya duele, probemos con tres emails reales.
            </h2>
          </div>
          <a
            href="mailto:founders@auyan.ai?subject=Founding%20Partner%20Auyan"
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
