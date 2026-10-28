import type { Metadata } from "next";
import { headers } from "next/headers";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages } from "next-intl/server";
import { ThemeProvider } from "next-themes";
import { Providers } from "@/components/providers";
import { Toaster } from "@/components/ui/sonner";
import { eneoTheme } from "@/theme/eneo";
import "./globals.css";

export const metadata: Metadata = {
  // Child routes/layouts set a string title → "<Page> · Eneo"; routes without
  // one fall back to "Eneo" (finding 1.1, ported from the Svelte per-page
  // <title>). Area layouts (admin / account / space) carry the area title so
  // their child pages inherit it without per-page boilerplate.
  title: { template: "%s · Eneo", default: "Eneo" },
  description: "Eneo"
};

export default async function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  const locale = await getLocale();
  const messages = await getMessages();
  // Per-request CSP nonce from src/proxy.ts. next-themes needs it for its
  // blocking colour-mode script (and its transition-suppressing <style>), and
  // client components that inject a <style> read it from Providers; the
  // nonce-only CSP would otherwise block them.
  const nonce = (await headers()).get("x-nonce") ?? undefined;

  return (
    <html
      lang={locale}
      // The Astryx theme scope, server-rendered so tokens exist on <html> (and
      // in portals) from first paint; the root <Theme> keeps it in sync.
      data-astryx-theme={eneoTheme.name}
      className="antialiased"
      suppressHydrationWarning
    >
      <head>
        {/* The UI font (globals.css "2b. Fonts"): every page needs it before
            first paint. The code and answer fonts load when first used. */}
        <link
          rel="preload"
          href="/fonts/figtree-latin-wght-normal.woff2"
          as="font"
          type="font/woff2"
          crossOrigin=""
        />
        {/* The rule Astryx's chat stream scroller would inject at runtime
            (scroll anchoring off while it follows new tokens), which the CSP
            blocks. Astryx skips its own injection when <head> already holds
            an element with this marker attribute. */}
        <style nonce={nonce} data-astryx-chat-following-style="" suppressHydrationWarning>
          {"[data-astryx-chat-following]{overflow-anchor:none !important}"}
        </style>
      </head>
      <body className="min-h-svh">
        <NextIntlClientProvider messages={messages}>
          {/* .light/.dark drive the legacy `dark:` variant and color-scheme
              (globals.css); data-theme is the attribute Astryx reads. */}
          <ThemeProvider
            attribute={["class", "data-theme"]}
            defaultTheme="system"
            enableSystem
            disableTransitionOnChange
            nonce={nonce}
          >
            <Providers nonce={nonce}>{children}</Providers>
            <Toaster />
          </ThemeProvider>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
