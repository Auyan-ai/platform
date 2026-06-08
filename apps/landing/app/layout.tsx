import './globals.css'

import type { Metadata } from 'next'
import { Geist, Geist_Mono } from 'next/font/google'
import Script from 'next/script'
import type { ReactNode } from 'react'
import { absoluteUrl, getSiteUrl, siteConfig } from '@/lib/site'

const geistSans = Geist({
  subsets: ['latin'],
  variable: '--font-geist-sans',
})

const geistMono = Geist_Mono({
  subsets: ['latin'],
  variable: '--font-geist-mono',
})

export const metadata: Metadata = {
  metadataBase: new URL(getSiteUrl()),
  title: {
    default: siteConfig.title,
    template: '%s | Auyan',
  },
  description: siteConfig.description,
  applicationName: siteConfig.name,
  keywords: [
    'AI customer support',
    'Shopify customer support',
    'CX e-commerce',
    'AI agent Shopify',
    'Gorgias AI',
    'Zendesk AI',
    'soporte ecommerce',
    'atención al cliente ecommerce',
  ],
  authors: [{ name: 'Auyan' }],
  creator: 'Auyan',
  publisher: 'Auyan',
  alternates: {
    canonical: absoluteUrl('/'),
  },
  openGraph: {
    title: siteConfig.title,
    description: siteConfig.description,
    url: absoluteUrl('/'),
    siteName: siteConfig.name,
    locale: siteConfig.locale,
    type: 'website',
    images: [
      {
        url: absoluteUrl('/opengraph-image'),
        width: 1200,
        height: 630,
        alt: siteConfig.title,
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: siteConfig.title,
    description: siteConfig.description,
    images: [absoluteUrl('/opengraph-image')],
    creator: siteConfig.twitter,
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      'max-image-preview': 'large',
      'max-snippet': -1,
      'max-video-preview': -1,
    },
  },
}

export default function RootLayout({ children }: { children: ReactNode }) {
  const plausibleDomain = process.env.NEXT_PUBLIC_PLAUSIBLE_DOMAIN
  const structuredData = {
    '@context': 'https://schema.org',
    '@graph': [
      {
        '@type': 'Organization',
        '@id': absoluteUrl('/#organization'),
        name: siteConfig.name,
        url: absoluteUrl('/'),
        email: siteConfig.founderEmail,
      },
      {
        '@type': 'WebSite',
        '@id': absoluteUrl('/#website'),
        name: siteConfig.name,
        url: absoluteUrl('/'),
        publisher: {
          '@id': absoluteUrl('/#organization'),
        },
        inLanguage: 'es',
      },
      {
        '@type': 'SoftwareApplication',
        '@id': absoluteUrl('/#software'),
        name: siteConfig.name,
        applicationCategory: 'BusinessApplication',
        operatingSystem: 'Web',
        url: absoluteUrl('/'),
        description: siteConfig.description,
        offers: {
          '@type': 'Offer',
          priceCurrency: 'EUR',
          price: '890',
          availability: 'https://schema.org/InStock',
        },
      },
    ],
  }

  return (
    <html lang="es" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body>
        <script type="application/ld+json">{JSON.stringify(structuredData)}</script>
        {plausibleDomain && (
          <Script
            defer
            data-domain={plausibleDomain}
            src="https://plausible.io/js/script.js"
            strategy="afterInteractive"
          />
        )}
        {children}
      </body>
    </html>
  )
}
