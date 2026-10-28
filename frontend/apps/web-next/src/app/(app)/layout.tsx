import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import type { Metadata } from "next";
import { cookies } from "next/headers";
import { QueryAppContextProvider } from "@/components/providers/app-context-from-queries";
import { loadAppContext } from "@/components/providers/app-context-queries";
import { AppShellFrame } from "@/components/shell/app-shell";
import {
  isSideNavCollapsed,
  SIDE_NAV_COLLAPSED_COOKIE
} from "@/components/shell/side-nav-preference";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { env } from "@/lib/env";
import { JobsProvider } from "@/features/jobs/use-jobs";
import { TourProvider } from "@/features/whats-new/tour-provider";
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
  const sideNavCollapsed = isSideNavCollapsed(
    (await cookies()).get(SIDE_NAV_COLLAPSED_COOKIE)?.value
  );
  const queryClient = getQueryClient();
  await loadAppContext(queryClient, eneoApi());

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <QueryAppContextProvider
        env={{
          showWebSearch: env.SHOW_WEB_SEARCH,
          links: {
            legacyApp: env.LEGACY_APP_URL ?? null,
            accessibilityStatement: env.ACCESSIBILITY_STATEMENT_URL ?? null,
            helpCenter: env.SHOW_HELP_CENTER ? (env.HELP_CENTER_URL ?? null) : null
          },
          frontendVersion: packageJson.version
        }}
      >
        <TourProvider>
          <JobsProvider>
            {/* Viewport-locked shell: pages scroll inside the page panel
                (main#main-content), so full-height surfaces (chat) can pin
                their input to the bottom. */}
            <AppShellFrame sideNavCollapsed={sideNavCollapsed}>{children}</AppShellFrame>
          </JobsProvider>
        </TourProvider>
      </QueryAppContextProvider>
    </HydrationBoundary>
  );
}
