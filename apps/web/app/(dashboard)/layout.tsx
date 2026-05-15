import type { ReactNode } from 'react'
import Link from 'next/link'
import { createClient } from '@/lib/supabase/server'
import { redirect } from 'next/navigation'

const LUNARIA_ID = '11111111-1111-1111-1111-111111111111'

export default async function DashboardLayout({ children }: { children: ReactNode }) {
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    redirect('/login')
  }

  return (
    <div className="flex min-h-screen bg-neutral-50">
      <aside className="fixed inset-y-0 left-0 z-50 flex w-60 flex-col bg-white border-r border-neutral-200">
        <div className="flex h-14 items-center border-b border-neutral-200 px-4">
          <span className="text-sm font-semibold tracking-tight">Auyan</span>
        </div>
        <nav className="flex-1 overflow-y-auto p-3 space-y-1 text-sm">
          <p className="px-2 py-1 text-xs font-medium text-neutral-400 uppercase tracking-wider">
            Lunaria
          </p>
          <Link
            href={`/tenants/${LUNARIA_ID}/conversations`}
            className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-neutral-600 hover:bg-neutral-100 hover:text-neutral-900"
          >
            <span>💬</span> Conversaciones
          </Link>
          <Link
            href={`/tenants/${LUNARIA_ID}/escalations`}
            className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-neutral-600 hover:bg-neutral-100 hover:text-neutral-900"
          >
            <span>🚨</span> Escalaciones
          </Link>
          {/* Tenant switcher se agrega en sub-PR 3.6 */}
        </nav>
      </aside>
      <main className="ml-60 flex-1 p-8">{children}</main>
    </div>
  )
}
