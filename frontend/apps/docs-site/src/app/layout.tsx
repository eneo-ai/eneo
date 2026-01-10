import { Footer, Layout, Navbar } from 'nextra-theme-docs'
import { Head } from 'nextra/components'
import { getPageMap } from 'nextra/page-map'

import './globals.css'

import EneoLogo from '@/components/EneoLogo'

export const metadata = {
  title: {
    default: 'Eneo - Democratic AI Platform',
    template: '%s | Eneo Docs'
  },
  description: 'Open-source AI platform for public sector organizations. Deploy and manage AI assistants with complete data sovereignty, GDPR compliance, and EU AI Act readiness.',
  keywords: ['AI platform', 'open source', 'public sector', 'GDPR', 'EU AI Act', 'data sovereignty', 'self-hosted AI'],
  authors: [{ name: 'Sundsvall Municipality & Ånge Municipality' }],
  openGraph: {
    title: 'Eneo - Democratic AI Platform',
    description: 'Open-source AI platform for public sector organizations',
    url: 'https://eneo.ai',
    siteName: 'Eneo Documentation',
    type: 'website',
  },
}

// const banner = <Banner storageKey="some-key">Nextra 4.0 is released 🎉</Banner>
const navbar = (
  <Navbar
    logo={<EneoLogo className="h-6" />}
  />
)
const footer = (
  <Footer>
    <div className="flex flex-col items-center gap-2">
      <div>
        AGPL-3.0 {new Date().getFullYear()} © Sundsvall Municipality & Ånge Municipality
      </div>
      <div className="text-sm opacity-70">
        Made with ❤️ by the Swedish Public Sector for the Global Community
      </div>
    </div>
  </Footer>
)

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      // Not required, but good for SEO
      lang="en"
      // Required to be set
      dir="ltr"
      // Suggested by `next-themes` package https://github.com/pacocoursey/next-themes#with-app
      suppressHydrationWarning
    >
      <Head
      // ... Your additional head options
      >
        {/* Your additional tags should be passed as `children` of `<Head>` element */}
      </Head>
      <body>
        <Layout
          navbar={navbar}
          pageMap={await getPageMap()}
          docsRepositoryBase="https://github.com/eneo-ai/eneo/tree/main/frontend/apps/docs-site"
          footer={footer}
        >
          {children}
        </Layout>
      </body>
    </html>
  )
}
