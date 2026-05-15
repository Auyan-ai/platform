import path from 'path'
import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  transpilePackages: ['@auyan/shared'],
  output: 'standalone',
  // Asegura que el trazado de archivos en standalone incluya packages/ del monorepo
  outputFileTracingRoot: path.join(__dirname, '../../'),
}

export default nextConfig
