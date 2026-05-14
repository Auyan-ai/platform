import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  // Permite importar TypeScript de packages/ sin paso de build previo
  transpilePackages: ['@auyan/shared'],
}

export default nextConfig
