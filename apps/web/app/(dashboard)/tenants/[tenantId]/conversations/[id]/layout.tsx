import type { ReactNode } from 'react'

export default function ConversationDetailLayout({ children }: { children: ReactNode }) {
  // Remove parent p-8 and fill viewport height so the chat thread can scroll properly.
  return <div className="-m-8 h-screen flex flex-col">{children}</div>
}
