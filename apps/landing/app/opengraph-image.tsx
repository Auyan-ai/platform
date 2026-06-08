import { ImageResponse } from 'next/og'
import { siteConfig } from '@/lib/site'

export const size = {
  width: 1200,
  height: 630,
}

export const contentType = 'image/png'

export default function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          background: '#FAFAF9',
          color: '#1C1917',
          padding: 72,
          fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif',
        }}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            fontSize: 28,
            fontWeight: 700,
          }}
        >
          <span>{siteConfig.name}</span>
          <span
            style={{
              border: '1px solid #D6D3D1',
              borderRadius: 999,
              padding: '10px 18px',
              color: '#1E40AF',
              fontSize: 24,
              fontWeight: 600,
            }}
          >
            Managed AI para Shopify CX
          </span>
        </div>
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 28,
          }}
        >
          <h1
            style={{
              margin: 0,
              maxWidth: 920,
              fontSize: 86,
              lineHeight: 0.98,
              letterSpacing: 0,
              fontWeight: 750,
            }}
          >
            AI agents for support that cannot feel automated.
          </h1>
          <p
            style={{
              margin: 0,
              maxWidth: 780,
              color: '#44403C',
              fontSize: 32,
              lineHeight: 1.35,
              fontWeight: 500,
            }}
          >
            Soporte Shopify, approvals humanos y mejora semanal sobre tickets reales.
          </p>
        </div>
        <div
          style={{
            display: 'flex',
            gap: 16,
            color: '#57534E',
            fontSize: 24,
            fontWeight: 600,
          }}
        >
          <span>Shadow mode</span>
          <span>·</span>
          <span>Review Queue</span>
          <span>·</span>
          <span>Weekly Reports</span>
        </div>
      </div>
    ),
    size,
  )
}
