import { PageShell } from '@/components/SiteShell'
import type { Metadata } from 'next'
import Link from 'next/link'
import {
  ArrowRight,
  Bot,
  ClipboardCheck,
  MessageSquareText,
  RefreshCw,
  ShieldCheck,
  ShoppingBag,
  Truck,
} from 'lucide-react'

export const metadata: Metadata = {
  title: 'AI Agent para Shopify CX',
  description:
    'Auyan opera agentes IA para soporte Shopify: pedidos, devoluciones, cambios, conocimiento de marca, approvals humanos y mejora semanal.',
}

const useCases = [
  ['Estado de pedido', Truck, 'Consulta órdenes, tracking y contexto de envío sin pedirle al cliente repetir datos.'],
  ['Cambios de dirección', ShieldCheck, 'Prepara la acción y espera aprobación humana cuando el cambio es sensible.'],
  ['Devoluciones y reembolsos', RefreshCw, 'Lee políticas, detecta ventanas y escala excepciones con contexto.'],
  ['Preguntas de producto', ShoppingBag, 'Responde usando KB curada, políticas y tono de marca.'],
] as const

const managedVsSelfServe = [
  ['Self-serve AI', 'Tu equipo configura intents, prompts, KB, evals y reglas cuando tiene tiempo.'],
  ['Auyan Managed AI', 'Auyan opera AOPs, shadow mode, approvals, reportes y mejoras semanales.'],
] as const

const flow = [
  ['Conecta', 'Shopify y helpdesk existente.'],
  ['Evalúa', 'Shadow mode con tickets reales.'],
  ['Activa', 'Categorías con evidencia suficiente.'],
  ['Mejora', 'Reporte semanal y propuestas concretas.'],
] as const

export default function ShopifyAiAgentPage() {
  return (
    <PageShell>
      <section className="relative overflow-hidden border-b border-border bg-background">
        <div className="absolute inset-0 bg-[linear-gradient(to_right,rgba(231,229,228,0.52)_1px,transparent_1px),linear-gradient(to_bottom,rgba(231,229,228,0.52)_1px,transparent_1px)] bg-[size:72px_72px] [mask-image:linear-gradient(to_bottom,black,transparent_82%)]" />
        <div className="relative mx-auto grid max-w-7xl gap-12 px-5 pb-20 pt-28 lg:grid-cols-[0.9fr_1.1fr] lg:items-center lg:pt-36">
          <div>
            <p className="inline-flex rounded-full border border-border bg-surface px-3 py-1 text-sm font-medium text-accent-foreground">
              AI Agent para Shopify CX
            </p>
            <h1 className="mt-6 max-w-3xl text-4xl font-semibold leading-[1.04] text-foreground sm:text-5xl md:text-7xl md:leading-[1.01]">
              Soporte Shopify con IA que tu equipo no tiene que mantener.
            </h1>
            <p className="mt-6 max-w-2xl text-lg leading-8 text-foreground-body">
              Auyan combina Shopify, helpdesk, knowledge base, approvals y operación humana para
              quitar carga repetitiva sin soltar el control de CX.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link
                href="/founding-partner"
                className="inline-flex h-11 items-center gap-2 rounded-full bg-accent px-5 text-sm font-medium text-foreground-on-accent transition-colors hover:bg-accent-hover"
              >
                Probar killer test
                <ArrowRight className="size-4" />
              </Link>
              <Link
                href="/security"
                className="inline-flex h-11 items-center rounded-full border border-border bg-surface px-5 text-sm font-medium text-foreground transition-colors hover:border-border-strong hover:bg-surface-muted"
              >
                Ver seguridad
              </Link>
            </div>
          </div>

          <div className="rounded-2xl border border-neutral-800 bg-neutral-950 p-5 text-white shadow-[0_34px_110px_rgba(15,23,42,0.22)]">
            <div className="flex items-center gap-3 border-b border-white/10 pb-4">
              <Bot className="size-5 text-cobalt-200" />
              <div>
                <p className="text-sm text-neutral-400">Shopify CX Agent</p>
                <p className="text-xl font-semibold">Intents, policies, approvals</p>
              </div>
            </div>
            <div className="mt-5 grid gap-3 sm:grid-cols-2">
              {useCases.map(([title, Icon, body]) => (
                <div key={title} className="rounded-xl border border-white/10 bg-white/[0.055] p-4">
                  <Icon className="size-5 text-cobalt-200" />
                  <p className="mt-4 font-semibold text-white">{title}</p>
                  <p className="mt-2 text-sm leading-6 text-neutral-300">{body}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="bg-surface py-20">
        <div className="mx-auto max-w-7xl px-5">
          <div className="max-w-3xl">
            <p className="text-sm font-medium text-accent-foreground">Managed vs self-serve</p>
            <h2 className="mt-4 text-3xl font-semibold leading-tight text-foreground md:text-5xl">
              El problema no es instalar IA. Es mantenerla cuando cambian tickets, políticas y
              clientes.
            </h2>
          </div>
          <div className="mt-10 grid gap-4 md:grid-cols-2">
            {managedVsSelfServe.map(([title, body], index) => (
              <div
                key={title}
                className={`rounded-2xl border p-6 ${
                  index === 1 ? 'border-accent bg-accent-subtle' : 'border-border bg-background'
                }`}
              >
                <h3 className="text-2xl font-semibold text-foreground">{title}</h3>
                <p className="mt-4 text-base leading-7 text-foreground-body">{body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="border-y border-border bg-background py-20">
        <div className="mx-auto grid max-w-7xl gap-8 px-5 lg:grid-cols-[0.82fr_1.18fr]">
          <div>
            <p className="text-sm font-medium text-accent-foreground">Cómo entra en producción</p>
            <h2 className="mt-4 text-3xl font-semibold leading-tight text-foreground md:text-5xl">
              Auyan activa categorías, no una caja negra completa.
            </h2>
            <p className="mt-4 text-lg leading-8 text-foreground-body">
              Empezamos por los motivos repetitivos con mejor señal y dejamos los casos complejos
              al equipo humano.
            </p>
          </div>
          <div className="grid gap-3">
            {flow.map(([title, body], index) => (
              <div key={title} className="rounded-xl border border-border bg-surface p-5">
                <div className="flex gap-4">
                  <span className="grid size-10 shrink-0 place-items-center rounded-full bg-accent text-sm font-semibold text-foreground-on-accent">
                    {index + 1}
                  </span>
                  <div>
                    <h3 className="text-lg font-semibold text-foreground">{title}</h3>
                    <p className="mt-2 text-sm leading-6 text-foreground-body">{body}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="bg-surface py-20">
        <div className="mx-auto grid max-w-7xl gap-6 px-5 md:grid-cols-3">
          {[
            ['Knowledge base curada', ClipboardCheck, 'No copiamos todo sin criterio. Priorizamos facts y políticas que afectan respuesta.'],
            ['Conversaciones completas', MessageSquareText, 'El agente trabaja con contexto de ticket, pedido y cliente cuando está disponible.'],
            ['Aprobación L3', ShieldCheck, 'Cambios sensibles pasan por humanos antes de tocar Shopify.'],
          ].map(([title, Icon, body]) => (
            <div key={title as string} className="rounded-xl border border-border bg-background p-6">
              <Icon className="size-6 text-accent-foreground" />
              <h3 className="mt-5 text-xl font-semibold text-foreground">{title as string}</h3>
              <p className="mt-3 text-sm leading-6 text-foreground-body">{body as string}</p>
            </div>
          ))}
        </div>
      </section>
    </PageShell>
  )
}
