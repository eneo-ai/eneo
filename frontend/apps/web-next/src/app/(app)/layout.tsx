import type { Metadata } from "next";
import { AppContextProvider, type AppContextData } from "@/components/providers/app-context";
import { AppShellFrame } from "@/components/shell/app-shell";
import { unwrap } from "@/lib/api/errors";
import { eneoApi } from "@/lib/api/server";
import { env } from "@/lib/env";
import { JobsProvider } from "@/features/jobs/use-jobs";
import { WhatsNewProvider } from "@/features/whats-new/whats-new-provider";
import { TourProvider } from "@/features/whats-new/tour-provider";
import { WhatsNewAnnouncement } from "@/features/whats-new/announcement";
import packageJson from "../../../package.json";

/** Every app page can be added to the home screen (public/manifest.json). */
export const metadata: Metadata = {
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    title: "Eneo"
  },
  other: {
    "mobile-web-app-capable": "yes"
  }
};

export default async function AppLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  const api = eneoApi();
  const [user, tenant, settings, federationStatus, limits, backendVersion, whatsNewState] =
    await Promise.all([
      unwrap(api.GET("/api/v1/users/me/")),
      unwrap(api.GET("/api/v1/users/tenant/")),
      unwrap(api.GET("/api/v1/settings/")),
      unwrap(api.GET("/api/v1/auth/federation-status")),
      unwrap(api.GET("/api/v1/limits/")),
      // The spec types /version as unknown; it returns a bare string.
      unwrap(api.GET("/version")).then((version) => (typeof version === "string" ? version : "")),
      // Optional during rolling deployments; an unavailable marker must not look like "never seen".
      unwrap(api.GET("/api/v1/whats-new/state/")).catch(() => null)
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
            {/* Viewport-locked shell: pages scroll inside the page panel
                (main#main-content), so full-height surfaces (chat) can pin
                their input to the bottom. */}
            <AppShellFrame>{children}</AppShellFrame>
          </JobsProvider>
        </TourProvider>
      </WhatsNewProvider>
    </AppContextProvider>
  );
}
