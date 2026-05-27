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
    <div data-density="compact" data-theme="mercury" className="min-h-screen bg-background">
      <Sidebar userEmail={user.email} />
      <div className="ml-[200px] min-h-screen">
        <AppTopbar actionLabel="Revisar mejoras" />
        <main className="px-6 pb-8 pt-10">
          <div className="mx-auto max-w-6xl">{children}</div>
        </main>
      </div>
    </div>
  )
}
