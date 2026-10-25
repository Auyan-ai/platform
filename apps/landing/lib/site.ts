export const siteConfig = {
  name: 'Auyan',
  title: 'Auyan — Managed AI para CX e-commerce',
  description:
    'Auyan opera agentes IA para equipos CX de e-commerce: soporte Shopify, approvals humanos, knowledge base curada y mejora semanal.',
  domain: 'auyan.ai',
  locale: 'es_ES',
  twitter: '@auyan_ai',
  founderEmail: 'founders@auyan.ai',
}

export const siteRoutes = [
  {
    path: '/',
    priority: 1,
    changeFrequency: 'weekly',
  },
  {
    path: '/founding-partner',
    priority: 0.95,
    changeFrequency: 'weekly',
  },
  {
    path: '/shopify-ai-agent',
    priority: 0.9,
    changeFrequency: 'weekly',
  },
  {
    path: '/pricing',
    priority: 0.85,
    changeFrequency: 'weekly',
  },
  {
    path: '/security',
    priority: 0.75,
    changeFrequency: 'monthly',
  },
  {
    path: '/about',
    priority: 0.5,
    changeFrequency: 'monthly',
  },
  {
    path: '/bot',
    priority: 0.3,
    changeFrequency: 'yearly',
  },
  {
    path: '/blog',
    priority: 0.5,
    changeFrequency: 'weekly',
  },
] as const

export function getSiteUrl() {
  return (process.env.NEXT_PUBLIC_SITE_URL ?? `https://${siteConfig.domain}`).replace(/\/$/, '')
}

export function absoluteUrl(path = '/') {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return `${getSiteUrl()}${normalizedPath}`
}
