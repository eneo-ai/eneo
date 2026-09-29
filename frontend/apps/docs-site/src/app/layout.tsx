import { Footer, Layout, Navbar } from "nextra-theme-docs";
import { Banner, Head } from "nextra/components";
import { getPageMap } from "nextra/page-map";

import "./globals.css";

import EneoLogo from "@/components/EneoLogo";
import VersionSwitcher from "@/components/VersionSwitcher";
import {
  getCurrentDocsVersion,
  getDocsVersions,
  getStableDocsVersion,
} from "@/lib/versions";

const versions = getDocsVersions();
const currentVersion = getCurrentDocsVersion();
const stableVersion = getStableDocsVersion();
const isStable = !currentVersion || currentVersion.kind === "stable";
const docsRef = process.env.NEXT_PUBLIC_DOCS_REF || "develop";

export const metadata = {
  title: {
    default: "Eneo - Democratic AI Platform",
    template: "%s | Eneo Docs",
  },
  description:
    "Open-source AI platform for public sector organizations. Deploy and manage AI assistants with complete data sovereignty, GDPR compliance, and EU AI Act readiness.",
  keywords: [
    "AI platform",
    "open source",
    "public sector",
    "GDPR",
    "EU AI Act",
    "data sovereignty",
    "self-hosted AI",
  ],
  authors: [{ name: "Sundsvall Municipality & Ånge Municipality" }],
  openGraph: {
    title: "Eneo - Democratic AI Platform",
    description: "Open-source AI platform for public sector organizations",
    url: "https://docs.eneo.ai",
    siteName: "Eneo Documentation",
    type: "website",
  },
  // Only the stable version should be indexed by search engines.
  ...(isStable ? {} : { robots: { index: false, follow: true } }),
};

const navbar = (
  <Navbar logo={<EneoLogo className="h-6" />}>
    {currentVersion && (
      <VersionSwitcher versions={versions} current={currentVersion} />
    )}
  </Navbar>
);

const banner =
  currentVersion && !isStable && stableVersion ? (
    <Banner dismissible={false}>
      {currentVersion.kind === "dev"
        ? "You are reading the development documentation for the next Eneo release. Features described here may not be available in the current release. "
        : `You are reading the documentation for Eneo ${currentVersion.label}, which is not the latest release. `}
      <a href={stableVersion.basePath || "/"} className="underline">
        Switch to {stableVersion.label} (latest)
      </a>
    </Banner>
  ) : undefined;

const footer = (
  <Footer>
    <div className="flex flex-col items-center gap-2">
      <div>
        AGPL-3.0 {new Date().getFullYear()} © Sundsvall Municipality & Ånge
        Municipality
      </div>
      <div className="text-sm opacity-70">
        Made with ❤️ by the Swedish Public Sector for the Global Community
      </div>
    </div>
  </Footer>
);

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      // Not required, but good for SEO
      lang="en"
      // Required to be set
      dir="ltr"
      // Suggested by `next-themes` package https://github.com/pacocoursey/next-themes#with-app
      suppressHydrationWarning
    >
      <Head />
      <body>
        <Layout
          banner={banner}
          navbar={navbar}
          pageMap={await getPageMap()}
          docsRepositoryBase={`https://github.com/eneo-ai/eneo/tree/${docsRef}/frontend/apps/docs-site`}
          footer={footer}
        >
          {children}
        </Layout>
      </body>
    </html>
  );
}
