import { HomePage } from '@/components/HomePage'
import { createPageMetadata } from '@/lib/metadata'

export const metadata = createPageMetadata({
  title: 'Managed AI para CX e-commerce',
  description:
    'Auyan opera agentes IA para marcas Shopify: soporte repetitivo, approvals humanos, shadow mode y mejora semanal sobre tickets reales.',
  path: '/',
})

export default function Page() {
  return <HomePage />
}
