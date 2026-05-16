const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export interface CurrentUser {
  user_id: string
  tenant_id: string | null
  role: string
  email: string
}

/**
 * Llama GET /users/me con el access token dado.
 * Retorna null si la llamada falla o el token es inválido.
 * Usable tanto en Server Components como en Client Components.
 */
export async function fetchCurrentUser(token: string): Promise<CurrentUser | null> {
  try {
    const resp = await fetch(`${API_URL}/users/me`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    })
    if (!resp.ok) return null
    return resp.json() as Promise<CurrentUser>
  } catch {
    return null
  }
}
