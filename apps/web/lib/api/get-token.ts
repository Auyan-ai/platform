'use client'

import { createClient } from '@/lib/supabase/client'

export async function getToken(): Promise<string> {
  const supabase = createClient()
  const {
    data: { session },
  } = await supabase.auth.getSession()
  if (!session?.access_token) throw new Error('Sin sesión activa')
  return session.access_token
}
