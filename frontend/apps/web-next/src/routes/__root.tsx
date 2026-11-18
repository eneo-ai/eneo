import { createRootRouteWithContext, HeadContent, Outlet } from "@tanstack/react-router";
import { EmbedProviders } from "@/features/widget/components/embed-providers";
import { ThemeProvider } from "next-themes";
import { AppIntlProvider } from "@/components/providers/intl-provider";
import { useBoot } from "@/boot-context";
import { Providers } from "@/components/providers";
import { BrowserSessionBoundary } from "@/components/providers/browser-session";
import { ThemeColor } from "@/components/providers/theme-color";
import { RouteAnnouncer } from "@/components/shell/route-announcer";
import { Toaster } from "@/components/ui/sonner";
import { rootHead } from "@/lib/route-head";
import type { RouterContext } from "@/router";

export const Route = createRootRouteWithContext<RouterContext>()({
  head: rootHead,
  component: Root
});

/** The embedded visitor document has its own theme and no app session. */
function Root() {
  const { locale, messages, nonce } = useBoot();
  const embed = /^(?:\/en)?\/embed\/[^/]+\/?$/.test(location.pathname);
  const requestedScheme = document.documentElement.dataset.eneoEmbedScheme;
  const scheme =
    requestedScheme === "light" || requestedScheme === "dark" ? requestedScheme : "system";
  if (embed)
    return (
      <AppIntlProvider locale={locale} messages={messages}>
        <EmbedProviders nonce={nonce} scheme={scheme}>
          <HeadContent />
          <Outlet />
        </EmbedProviders>
      </AppIntlProvider>
    );
  return (
    <AppIntlProvider locale={locale} messages={messages}>
      {/* .light/.dark drive the legacy `dark:` variant and color-scheme
          (globals.css); data-theme is the attribute Astryx reads. */}
      <ThemeProvider
        attribute={["class", "data-theme"]}
        defaultTheme="system"
        enableSystem
        disableTransitionOnChange
        nonce={nonce}
      >
        <Providers nonce={nonce}>
          <HeadContent />
          <RouteAnnouncer />
          <BrowserSessionBoundary>
            <Outlet />
          </BrowserSessionBoundary>
        </Providers>
        <Toaster />
        <ThemeColor />
      </ThemeProvider>
    </AppIntlProvider>
  );
}
