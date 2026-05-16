import type { ReactNode } from 'react'

export default function ClientConversationDetailLayout({ children }: { children: ReactNode }) {
  return <div className="-m-8 h-screen flex flex-col">{children}</div>
}
