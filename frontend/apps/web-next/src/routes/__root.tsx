import { createRootRouteWithContext, HeadContent, Outlet } from "@tanstack/react-router";
import { ThemeProvider } from "next-themes";
import { IntlProvider } from "use-intl";
import { useBoot } from "@/boot-context";
import { Providers } from "@/components/providers";
import { ThemeColor } from "@/components/providers/theme-color";
import { RouteAnnouncer } from "@/components/shell/route-announcer";
import { Toaster } from "@/components/ui/sonner";
import { rootHead } from "@/lib/route-head";
import type { RouterContext } from "@/router";

// The viewer's own zone, set explicitly (plan §2.2). P3-intl's AppIntlProvider
// becomes its one owner and replaces this IntlProvider.
const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;

export const Route = createRootRouteWithContext<RouterContext>()({
  head: rootHead,
  component: Root
});

/** The providers of the Next root layout (src/app/layout.tsx), in its order. */
function Root() {
  const { locale, messages, nonce } = useBoot();
  return (
    <IntlProvider locale={locale} messages={messages} timeZone={timeZone}>
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
          <Outlet />
        </Providers>
        <Toaster />
        <ThemeColor />
      </ThemeProvider>
    </IntlProvider>
  );
}
