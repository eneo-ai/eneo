import { AppContextProvider, type AppContextData } from "@/components/providers/app-context";
import { Header } from "@/components/shell/header";
import { unwrap } from "@/lib/api/errors";
import { eneoApi } from "@/lib/api/server";
import { env } from "@/lib/env";
import { JobsProvider } from "@/features/jobs/use-jobs";
import { WhatsNewProvider } from "@/features/whats-new/whats-new-provider";
import { TourProvider } from "@/features/whats-new/tour-provider";
import { WhatsNewAnnouncement } from "@/features/whats-new/announcement";
import { getTranslations } from "next-intl/server";
import packageJson from "../../../package.json";

export default async function AppLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  const api = eneoApi();
  const [user, tenant, settings, federationStatus, limits, backendVersion, whatsNewState, t] =
    await Promise.all([
      unwrap(api.GET("/api/v1/users/me/")),
      unwrap(api.GET("/api/v1/users/tenant/")),
      unwrap(api.GET("/api/v1/settings/")),
      unwrap(api.GET("/api/v1/auth/federation-status")),
      unwrap(api.GET("/api/v1/limits/")),
      // The spec types /version as unknown; it returns a bare string.
      unwrap(api.GET("/version")).then((version) => (typeof version === "string" ? version : "")),
      // Optional during rolling deployments; an unavailable marker must not look like "never seen".
      unwrap(api.GET("/api/v1/whats-new/state/")).catch(() => null),
      getTranslations()
    ]);

  const value: AppContextData = {
    user,
    tenant,
    settings,
    federationStatus,
    limits,
    featureFlags: {
      showWebSearch: env.SHOW_WEB_SEARCH
    },
    links: {
      accessibilityStatement: env.ACCESSIBILITY_STATEMENT_URL ?? null
    },
    versions: { frontend: packageJson.version, backend: backendVersion }
  };

  return (
    <AppContextProvider value={value}>
      <WhatsNewProvider
        key={`${settings.whats_new_enabled !== false}:${whatsNewState?.seen_version ?? "unknown"}:${whatsNewState?.announced_version ?? "unknown"}`}
        enabled={settings.whats_new_enabled !== false}
        initialSeen={whatsNewState?.seen_version}
        initialAnnounced={whatsNewState?.announced_version}
      >
        <TourProvider>
          <JobsProvider>
            <WhatsNewAnnouncement />
            {/* Viewport-locked shell: pages scroll inside main, so full-height
            surfaces (chat) can pin their input to the bottom. */}
            <div className="flex h-svh flex-col">
              <a
                href="#main-content"
                className="focus:bg-background focus:text-foreground sr-only focus:not-sr-only focus:absolute focus:top-3 focus:left-3 focus:z-50 focus:rounded-md focus:border focus:px-3 focus:py-2 focus:shadow"
              >
                {t("skip_to_content")}
              </a>
              <Header />
              {/* tabIndex -1: the skip link moves focus here, not just the
                  scroll position (WCAG 2.4.1); tests/a11y.spec.ts checks it. */}
              <main
                id="main-content"
                tabIndex={-1}
                className="flex min-h-0 flex-1 flex-col overflow-y-auto focus:outline-none"
              >
                {children}
              </main>
            </div>
          </JobsProvider>
        </TourProvider>
      </WhatsNewProvider>
    </AppContextProvider>
  );
}
