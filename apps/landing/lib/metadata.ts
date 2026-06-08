import type { Metadata } from 'next'
import { absoluteUrl, siteConfig } from './site'

type PageMetadataInput = {
  title: string
  description: string
  path: string
}

export function createPageMetadata({ title, description, path }: PageMetadataInput): Metadata {
  const url = absoluteUrl(path)
  const socialTitle = title.includes('Auyan') ? title : `${title} | Auyan`

  return {
    title,
    description,
    alternates: {
      canonical: url,
    },
    openGraph: {
      title: socialTitle,
      description,
      url,
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
      title: socialTitle,
      description,
      images: [absoluteUrl('/opengraph-image')],
      creator: siteConfig.twitter,
    },
  }
}
