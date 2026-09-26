"use client";

import { InternationalizationProvider, type MessagesByLocale } from "@astryxdesign/core/i18n";
import { LinkProvider } from "@astryxdesign/core/Link";
import { Theme } from "@astryxdesign/core/theme";
import astryxSv from "@astryxdesign/core/locales/sv-SE.json";
import Link from "next/link";
import { useLocale } from "next-intl";
import { useTheme } from "next-themes";
import { useHydrated } from "@/lib/hooks/use-hydrated";
import { eneoTheme } from "@/theme/eneo";

// Astryx's own component strings (aria labels, pagination, close buttons…).
// English ships built in; Swedish comes from Astryx's catalog, keyed by our
// next-intl locale code.
const ASTRYX_MESSAGES: MessagesByLocale = { sv: astryxSv };

/**
 * next/link for Astryx links. Astryx passes the target as both `href` and
 * `to` (for routers that read `to`); next/link would leave `to` on the <a>
 * as an invalid attribute.
 */
function NextLink({ children, ...props }: React.ComponentProps<typeof Link> & { to?: string }) {
  delete props.to;
  return <Link {...props}>{children}</Link>;
}

/**
 * Root of the Astryx component library: the (pre-built) Eneo theme, Astryx
 * strings in the active next-intl locale, and next/link for Astryx links.
 *
 * next-themes owns the colour mode: its blocking script sets .light/.dark and
 * data-theme on <html> before first paint, and globals.css pins color-scheme
 * to that class. Astryx only mirrors the resolved mode once hydrated; until
 * then it gets "system" so server and client markup match.
 */
export function AstryxProvider({ children }: { children: React.ReactNode }) {
  const { resolvedTheme } = useTheme();
  const hydrated = useHydrated();
  const locale = useLocale();
  const mode =
    hydrated && (resolvedTheme === "light" || resolvedTheme === "dark") ? resolvedTheme : "system";

  return (
    <Theme theme={eneoTheme} mode={mode}>
      <InternationalizationProvider locale={locale} messages={ASTRYX_MESSAGES}>
        <LinkProvider component={NextLink}>{children}</LinkProvider>
      </InternationalizationProvider>
    </Theme>
  );
}
