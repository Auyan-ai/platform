import type { ReactNode } from 'react'
import { createClient } from '@/lib/supabase/server'
import { redirect } from 'next/navigation'
import { Sidebar } from '@/components/nav/Sidebar'
import { AppTopbar } from '@/components/nav/AppTopbar'

export default async function DashboardLayout({ children }: { children: ReactNode }) {
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    redirect('/login')
  }

  return (
    <div data-density="compact" data-theme="mercury" className="flex min-h-screen bg-background">
      <Sidebar userEmail={user.email} />
      <AppTopbar label={user.email ?? 'Auyan'} actionLabel="Revisar mejoras" />
      <main className="ml-60 flex-1 px-6 pb-8 pt-24">
        <div className="mx-auto max-w-6xl">{children}</div>
      </main>
    </div>
  )
}
