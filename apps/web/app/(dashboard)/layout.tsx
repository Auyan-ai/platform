import type { ReactNode } from 'react'
import { createClient } from '@/lib/supabase/server'
import { redirect } from 'next/navigation'

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
        <nav className="flex-1 overflow-y-auto p-3 text-sm text-neutral-600">
          {/* Tenant switcher y nav se agregan en sub-PR 3.6 */}
          <p className="px-2 py-1 text-xs text-neutral-400">Selecciona un tenant</p>
        </nav>
      </aside>
      <main className="ml-60 flex-1 p-8">{children}</main>
    </div>
  )
}
