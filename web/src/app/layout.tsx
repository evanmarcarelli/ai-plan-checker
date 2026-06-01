import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Plan Room AHJ',
  description: 'AI-assisted plan check triage for building departments',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full">{children}</body>
    </html>
  )
}
