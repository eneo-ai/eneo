import { createFileRoute, Outlet } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { AppFrame } from "@/components/shell/app-frame";
import { readSideNavCollapsedCookie } from "@/components/shell/side-nav-preference";
import { browserApi } from "@/lib/api/browser";
import { readCached } from "@/lib/api/query";
import { requireBrowserSession } from "@/lib/api/refusal";
import { loadSession, sessionQueries } from "@/lib/api/session";
import { runtimeConfig } from "@/lib/runtime-config";
import packageJson from "../../package.json";

export const Route = createFileRoute("/_app")({
  beforeLoad: async ({ context }) => {
    await requireBrowserSession();
    await readCached(context.queryClient, sessionQueries(browserApi).me);
    // Start the other resources together. Their mounted readers own pending/error UI.
    void loadSession(context.queryClient, browserApi).catch(() => {});
  },
  pendingComponent: () => null,
  component: AppLayout
});

function AppLayout() {
  const [sideNavCollapsed] = useState(readSideNavCollapsedCookie);
  const config = runtimeConfig();
  const env = useMemo(
    () => ({
      links: {
        legacyApp: config.legacy_app_url,
        accessibilityStatement: config.accessibility_statement_url,
        helpCenter: config.help_center_url
      },
      frontendVersion: packageJson.version,
      backendVersion: config.version,
      federationEnabled: config.federation_enabled
    }),
    [config]
  );
  return (
    <AppFrame env={env} sideNavCollapsed={sideNavCollapsed}>
      <Outlet />
    </AppFrame>
  );
}
