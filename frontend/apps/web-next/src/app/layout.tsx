import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Source_Serif_4 } from "next/font/google";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages } from "next-intl/server";
import { ThemeProvider } from "next-themes";
import { Providers } from "@/components/providers";
import { Toaster } from "@/components/ui/sonner";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"]
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"]
});

// Serif "voice" for assistant answers — signals who's speaking (content to read)
// vs the sans UI chrome around it. Applied via --font-voice on MessageResponse.
const sourceSerif = Source_Serif_4({
  variable: "--font-source-serif",
  subsets: ["latin"]
});

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

  return (
    <html
      lang={locale}
      className={`${inter.variable} ${jetbrainsMono.variable} ${sourceSerif.variable} antialiased`}
      suppressHydrationWarning
    >
      <body className="min-h-svh">
        <NextIntlClientProvider messages={messages}>
          <ThemeProvider
            attribute="class"
            defaultTheme="system"
            enableSystem
            disableTransitionOnChange
          >
            <Providers>{children}</Providers>
            <Toaster />
          </ThemeProvider>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
