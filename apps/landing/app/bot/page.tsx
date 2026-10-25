import { PageShell } from '@/components/SiteShell'
import { createPageMetadata } from '@/lib/metadata'
import { siteConfig } from '@/lib/site'

export const metadata = createPageMetadata({
  title: 'AuyanBot',
  description:
    'AuyanBot es el rastreador de Auyan. Qué lee de las webs de e-commerce, con qué límites y cómo bloquearlo.',
  path: '/bot',
})

const userAgent = 'AuyanBot/<versión> (+https://auyan.es/bot)'

const reads = [
  'La Storefront API pública de Shopify y su Storefront MCP.',
  'Los archivos llms.txt, llms-full.txt y agents.md, si existen.',
  'El sitemap y las páginas de ayuda y políticas: envíos, devoluciones, preguntas frecuentes y contacto.',
] as const

const limits = [
  'Respeta robots.txt.',
  'Máximo 2 peticiones simultáneas por dominio.',
  'Unas 150 peticiones por ejecución.',
  'Si recibe un 429, espera lo que indique Retry-After y, si se repite, abandona esa fuente.',
] as const

const readsEn = [
  'The official public Shopify Storefront API and Storefront MCP.',
  'llms.txt, llms-full.txt and agents.md files, when present.',
  'The sitemap and key help and policy pages (shipping, returns, FAQ, contact).',
] as const

const h2 = 'text-2xl font-semibold text-foreground md:text-3xl'
const p = 'mt-4 text-base leading-7 text-foreground-body'
const ul = 'mt-4 list-disc space-y-2 pl-6 text-base leading-7 text-foreground-body'
const pre =
  'mt-4 overflow-x-auto rounded-xl border border-border bg-surface p-4 font-mono text-sm text-foreground'

export default function BotPage() {
  const email = siteConfig.founderEmail

  return (
    <PageShell>
      <section className="border-b border-border bg-background">
        <div className="mx-auto max-w-3xl px-5 pb-12 pt-28 lg:pt-36">
          <p className="inline-flex rounded-full border border-border bg-surface px-3 py-1 text-sm font-medium text-accent-foreground">
            Rastreador
          </p>
          <h1 className="mt-6 text-4xl font-semibold leading-[1.04] text-foreground sm:text-5xl">
            AuyanBot
          </h1>
          <p className="mt-6 text-lg leading-8 text-foreground-body">
            AuyanBot lee el sitio web público de una tienda online para configurar su agente de
            atención al cliente. Solo lo hace con tiendas que son clientes de Auyan o que están en
            una conversación comercial con nosotros.
          </p>
        </div>
      </section>

      <section className="bg-surface py-12">
        <div className="mx-auto max-w-3xl space-y-12 px-5">
          <div>
            <h2 className={h2}>Cómo se identifica</h2>
            <p className={p}>Cada petición lleva este User-Agent:</p>
            <pre className={pre}>{userAgent}</pre>
          </div>

          <div>
            <h2 className={h2}>Qué lee</h2>
            <ul className={ul}>
              {reads.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
            <p className={p}>
              No entra en el checkout, los carritos, las cuentas de usuario ni los formularios.
            </p>
          </div>

          <div>
            <h2 className={h2}>Cómo se comporta</h2>
            <ul className={ul}>
              {limits.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>

          <div>
            <h2 className={h2}>Cómo bloquearlo</h2>
            <p className={p}>Añade esto a tu robots.txt:</p>
            <pre className={pre}>{'User-agent: AuyanBot\nDisallow: /'}</pre>
            <p className={p}>AuyanBot lo respeta en su siguiente ejecución.</p>
          </div>

          <div>
            <h2 className={h2}>Preguntas</h2>
            <p className={p}>
              Escríbenos a{' '}
              <a className="font-medium text-accent-foreground underline" href={`mailto:${email}`}>
                {email}
              </a>
              .
            </p>
          </div>
        </div>
      </section>

      <section lang="en" className="border-t border-border bg-background py-12">
        <div className="mx-auto max-w-3xl px-5">
          <h2 className={h2}>AuyanBot in English</h2>
          <p className={p}>
            AuyanBot is Auyan&apos;s crawler. It reads the public website of an online store to
            configure that store&apos;s customer-service agent, only for stores that are Auyan
            clients or in a sales conversation with us. Its User-Agent is{' '}
            <code className="font-mono text-sm">{userAgent}</code>.
          </p>
          <p className={p}>It reads:</p>
          <ul className={ul}>
            {readsEn.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <p className={p}>
            It never touches checkout, carts, accounts or forms. It obeys robots.txt, makes at most
            2 concurrent requests per domain and about 150 requests per run, and honors Retry-After
            on a 429. To block it, add{' '}
            <code className="font-mono text-sm">User-agent: AuyanBot</code> and{' '}
            <code className="font-mono text-sm">Disallow: /</code> to your robots.txt. Questions:{' '}
            <a className="font-medium text-accent-foreground underline" href={`mailto:${email}`}>
              {email}
            </a>
            .
          </p>
        </div>
      </section>
    </PageShell>
  )
}
