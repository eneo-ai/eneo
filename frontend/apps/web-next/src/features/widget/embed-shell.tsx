import { NextIntlClientProvider } from "next-intl";
import { EmbedProviders } from "./components/embed-providers";
import type { EmbedScheme } from "./server/embed-policy";
import type { Locale } from "@/lib/i18n/locales";
import { eneoTheme } from "@/theme/eneo";

/**
 * The document of an embed page (src/app/layout.tsx renders it in place of
 * the app's): the widget's language and the colour scheme the proxy decided
 * from its configuration, server-rendered so the first paint is right.
 * No next-themes: the scheme is the host page's or the widget's own, never
 * the visitor's stored preference for this origin. Astryx's <Theme> keeps
 * `data-theme` in step once the page runs (embed-providers.tsx).
 */
export async function EmbedShell({
  locale,
  scheme,
  nonce,
  className,
  children
}: {
  locale: Locale;
  scheme: EmbedScheme;
  nonce: string | undefined;
  className: string;
  children: React.ReactNode;
}) {
  const messages = (await import(`@/lib/i18n/messages/${locale}.json`)).default;
  return (
    <html
      lang={locale}
      data-astryx-theme={eneoTheme.name}
      data-theme={scheme === "system" ? undefined : scheme}
      className={className}
      suppressHydrationWarning
    >
      <body className="min-h-svh">
        <NextIntlClientProvider locale={locale} messages={messages}>
          <EmbedProviders nonce={nonce} scheme={scheme}>
            {children}
          </EmbedProviders>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
