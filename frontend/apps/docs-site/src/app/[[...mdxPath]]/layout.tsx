import { Footer, Layout, Navbar } from "nextra-theme-docs";
import { Banner, Head, Search } from "nextra/components";
import { getPageMap } from "nextra/page-map";

import "../globals.css";

import EneoLogo from "@/components/EneoLogo";
import VersionSwitcher from "@/components/VersionSwitcher";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import { hasSwedishPages, languagePath, splitDocsPath } from "@/lib/languages";
import { getSourceRoutes } from "@/lib/content";
import { languagePageMap } from "@/lib/navigation";
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
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ mdxPath?: string[] }>;
}) {
  const { mdxPath = [] } = await params;
  const { language, page } = splitDocsPath(`/${mdxPath.join("/")}`);
  const sv = language === "sv";
  const canSearch = !sv || hasSwedishPages(await getSourceRoutes());
  const navbar = (
    <Navbar
      logo={<EneoLogo className="h-6" />}
      logoLink={languagePath("/", language)}
    >
      <LanguageSwitcher />
      {currentVersion && (
        <VersionSwitcher versions={versions} current={currentVersion} />
      )}
    </Navbar>
  );
  const banner =
    currentVersion && !isStable && stableVersion ? (
      <Banner dismissible={false}>
        {currentVersion.kind === "dev"
          ? sv
            ? "Du läser utvecklingsdokumentationen för nästa Eneo-version. Funktionerna kanske inte finns i den aktuella utgåvan. "
            : "You are reading the development documentation for the next Eneo release. Features described here may not be available in the current release. "
          : sv
            ? `Du läser dokumentationen för Eneo ${currentVersion.label}, som inte är den senaste utgåvan. `
            : `You are reading the documentation for Eneo ${currentVersion.label}, which is not the latest release. `}
        <a
          href={`${stableVersion.basePath}${languagePath("/", language)}`}
          className="underline"
        >
          {sv
            ? `Visa ${stableVersion.label} (senaste)`
            : `Switch to ${stableVersion.label} (latest)`}
        </a>
      </Banner>
    ) : undefined;
  return (
    <html
      // Not required, but good for SEO
      lang={language}
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
          pageMap={languagePageMap(await getPageMap(), language)}
          docsRepositoryBase={`https://github.com/eneo-ai/eneo/tree/${docsRef}/frontend/apps/docs-site`}
          footer={footer}
          search={
            canSearch ? (
              <Search
                placeholder={
                  sv ? "Sök i dokumentationen…" : "Search documentation…"
                }
                emptyResult={
                  sv
                    ? "Inga resultat. Sidor utan svensk översättning finns i den engelska sökningen."
                    : "No results found."
                }
                loading={sv ? "Söker…" : "Loading…"}
                errorText={
                  sv
                    ? "Kunde inte ladda sökindexet."
                    : "Failed to load search index."
                }
              />
            ) : (
              <a
                className="text-sm underline"
                href={`${process.env.NEXT_PUBLIC_BASE_PATH || ""}${page}`}
              >
                Svenska översättningar saknas. Sök på engelska.
              </a>
            )
          }
          editLink={sv ? "Redigera sidan" : "Edit this page"}
          feedback={{
            content: sv
              ? "Frågor? Lämna synpunkter"
              : "Question? Give us feedback",
          }}
          toc={{
            title: sv ? "På den här sidan" : "On This Page",
            backToTop: sv ? "Till toppen" : "Scroll to top",
          }}
          themeSwitch={{
            dark: sv ? "Mörkt" : "Dark",
            light: sv ? "Ljust" : "Light",
            system: "System",
          }}
        >
          {children}
        </Layout>
      </body>
    </html>
  );
}
