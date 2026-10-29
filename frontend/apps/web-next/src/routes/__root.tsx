import { createRootRouteWithContext, HeadContent, Outlet } from "@tanstack/react-router";
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

/** The providers of the Next root layout (src/app/layout.tsx), in its order. */
function Root() {
  const { locale, messages, nonce } = useBoot();
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
