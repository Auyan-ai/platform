import type { ReactNode } from 'react'

export default function ClientInsightDetailLayout({ children }: { children: ReactNode }) {
  return <div className="-m-8 flex h-screen flex-col">{children}</div>
}
