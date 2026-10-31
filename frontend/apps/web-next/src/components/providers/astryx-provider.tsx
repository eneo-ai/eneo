"use client";

import { InternationalizationProvider, type MessagesByLocale } from "@astryxdesign/core/i18n";
import { LinkProvider } from "@astryxdesign/core/Link";
import { Theme } from "@astryxdesign/core/theme";
import astryxSv from "@astryxdesign/core/locales/sv-SE.json";
import Link from "@/lib/link";
import { useLocale } from "use-intl";
import { eneoTheme } from "@/theme/eneo";

// Astryx's own component strings (aria labels, pagination, close buttons…).
// English ships built in; Swedish comes from Astryx's catalog, keyed by our
// use-intl locale code.
const ASTRYX_MESSAGES: MessagesByLocale = { sv: astryxSv };

/**
 * Astryx passes both `href` and `to`; the app's Link accepts `href`.
 */
function AstryxLink({ children, ...props }: React.ComponentProps<typeof Link> & { to?: string }) {
  delete props.to;
  return <Link {...props}>{children}</Link>;
}

/**
 * Root of the Astryx component library: the (pre-built) Eneo theme, Astryx
 * strings in the active use-intl locale, and app navigation for Astryx links.
 *
 * next-themes owns the colour mode: index.html sets .light/.dark and
 * data-theme on <html> before first paint, and globals.css (section 5) pins
 * color-scheme to that class, so Astryx's light-dark() tokens follow it.
 * Astryx stays on mode="system" so CSS follows the same document setting.
 */
export function AstryxProvider({ children }: { children: React.ReactNode }) {
  const locale = useLocale();

  return (
    <Theme theme={eneoTheme} mode="system">
      <InternationalizationProvider locale={locale} messages={ASTRYX_MESSAGES}>
        <LinkProvider component={AstryxLink}>{children}</LinkProvider>
      </InternationalizationProvider>
    </Theme>
  );
}
