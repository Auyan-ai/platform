import { PageShell } from '@/components/SiteShell'
import { createPageMetadata } from '@/lib/metadata'
import Link from 'next/link'
import {
  ArrowRight,
  ClipboardCheck,
  Eye,
  FileLock2,
  KeyRound,
  LockKeyhole,
  ShieldCheck,
  UserCheck,
} from 'lucide-react'

export const metadata = createPageMetadata({
  title: 'Seguridad Auyan',
  description:
    'Cómo Auyan protege operaciones CX e-commerce: permisos por acción, approvals humanos, aislamiento por tenant y conexión sobre tu helpdesk actual.',
  path: '/security',
})

const pillars = [
  {
    title: 'Aislamiento por cliente',
    body: 'El dashboard interno y la vista cliente respetan fronteras de tenant. Cada operación se evalúa con contexto del cliente correspondiente.',
    icon: ShieldCheck,
  },
  {
    title: 'Permisos por acción',
    body: 'Las skills de Shopify se separan por sensibilidad. Lecturas, cambios y acciones comerciales no tienen el mismo nivel de permiso.',
    icon: KeyRound,
  },
  {
    title: 'Approval gates',
    body: 'Acciones L3 como cambios sensibles, reembolsos o cancelaciones esperan aprobación humana antes de ejecutarse.',
    icon: UserCheck,
  },
  {
    title: 'Auditoría operativa',
    body: 'Auyan registra decisiones, inputs y ejecuciones para revisar qué propuso la IA y qué aprobó una persona.',
    icon: ClipboardCheck,
  },
] as const

const boundaries = [
  ['No creamos un canal paralelo', 'Auyan se conecta al helpdesk existente y hereda sus canales.'],
  ['No movemos credenciales al dashboard cliente', 'La operación sensible se mantiene en backend y flujos internos controlados.'],
  ['No ejecutamos L3 sin permiso', 'La IA puede proponer, pero cambios sensibles requieren gate humano.'],
  ['No prometemos compliance enterprise inventado', 'La página pública describe controles reales del producto actual.'],
] as const

const dataFlow = [
  ['Helpdesk', 'Mensajes, estado del ticket y contexto conversacional.'],
  ['Auyan Agent OS', 'Clasificación, AOPs, KB, propuestas y trazas.'],
  ['Shopify', 'Lecturas y acciones permitidas según intención y nivel.'],
  ['Human approval', 'Revisión para cambios sensibles antes de tocar sistemas externos.'],
] as const

export default function SecurityPage() {
  return (
    <PageShell>
      <section className="relative overflow-hidden border-b border-border bg-background">
        <div className="absolute inset-0 bg-[linear-gradient(to_right,rgba(231,229,228,0.52)_1px,transparent_1px),linear-gradient(to_bottom,rgba(231,229,228,0.52)_1px,transparent_1px)] bg-[size:72px_72px] [mask-image:linear-gradient(to_bottom,black,transparent_82%)]" />
        <div className="relative mx-auto grid max-w-7xl gap-12 px-5 pb-20 pt-28 lg:grid-cols-[0.9fr_1.1fr] lg:items-center lg:pt-36">
          <div>
            <p className="inline-flex rounded-full border border-border bg-surface px-3 py-1 text-sm font-medium text-accent-foreground">
              Seguridad y control
            </p>
            <h1 className="mt-6 max-w-3xl text-4xl font-semibold leading-[1.04] text-foreground sm:text-5xl md:text-7xl md:leading-[1.01]">
              IA con límites claros antes de tocar tu operación.
            </h1>
            <p className="mt-6 max-w-2xl text-lg leading-8 text-foreground-body">
              Auyan está diseñado para operar encima de tu stack, no para reemplazarlo con una caja
              negra. Las acciones sensibles se separan, se auditan y pasan por aprobación humana.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <a
                href="mailto:founders@auyan.ai?subject=Security%20review%20Auyan"
                className="inline-flex h-11 items-center gap-2 rounded-full bg-accent px-5 text-sm font-medium text-foreground-on-accent transition-colors hover:bg-accent-hover"
              >
                Hablar de seguridad
                <ArrowRight className="size-4" />
              </a>
              <Link
                href="/founding-partner"
                className="inline-flex h-11 items-center rounded-full border border-border bg-surface px-5 text-sm font-medium text-foreground transition-colors hover:border-border-strong hover:bg-surface-muted"
              >
                Ver onboarding
              </Link>
            </div>
          </div>

          <div className="rounded-2xl border border-neutral-800 bg-neutral-950 p-5 text-white shadow-[0_34px_110px_rgba(15,23,42,0.22)]">
            <div className="flex items-center gap-3 border-b border-white/10 pb-4">
              <LockKeyhole className="size-5 text-cobalt-200" />
              <div>
                <p className="text-sm text-neutral-400">Control plane</p>
                <p className="text-xl font-semibold">Approve before execute</p>
              </div>
            </div>
            <div className="mt-5 grid gap-3">
              {dataFlow.map(([title, body], index) => (
                <div key={title} className="rounded-xl border border-white/10 bg-white/[0.055] p-4">
                  <div className="flex gap-3">
                    <span className="grid size-8 shrink-0 place-items-center rounded-full bg-white text-sm font-semibold text-neutral-950">
                      {index + 1}
                    </span>
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
            <p className="text-sm font-medium text-accent-foreground">Controles</p>
            <h2 className="mt-4 text-3xl font-semibold leading-tight text-foreground md:text-5xl">
              La frontera importante no es “IA sí o no”. Es qué puede hacer.
            </h2>
          </div>
          <div className="mt-10 grid gap-4 md:grid-cols-2">
            {pillars.map(({ title, body, icon: Icon }) => (
              <div key={title} className="rounded-xl border border-border bg-background p-6">
                <Icon className="size-6 text-accent-foreground" />
                <h3 className="mt-5 text-xl font-semibold text-foreground">{title}</h3>
                <p className="mt-3 text-sm leading-6 text-foreground-body">{body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="border-y border-border bg-background py-20">
        <div className="mx-auto grid max-w-7xl gap-8 px-5 lg:grid-cols-[0.82fr_1.18fr]">
          <div>
            <p className="text-sm font-medium text-accent-foreground">Límites explícitos</p>
            <h2 className="mt-4 text-3xl font-semibold leading-tight text-foreground md:text-5xl">
              La confianza también se construye diciendo qué no hacemos.
            </h2>
          </div>
          <div className="grid gap-3">
            {boundaries.map(([title, body]) => (
              <div key={title} className="rounded-xl border border-border bg-surface p-5">
                <div className="flex gap-3">
                  <FileLock2 className="mt-1 size-5 shrink-0 text-accent-foreground" />
                  <div>
                    <h3 className="font-semibold text-foreground">{title}</h3>
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
            ['PII con cuidado', Eye, 'La copia forense puede redactar datos sensibles cuando no hacen falta para operar.'],
            ['Stack existente', ShieldCheck, 'Auyan hereda canales del helpdesk, en vez de duplicar conversaciones.'],
            ['Humano en el loop', UserCheck, 'Tu equipo conserva criterio sobre casos complejos, tono y excepciones.'],
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
