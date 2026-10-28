"use client";

import { InternationalizationProvider } from "@astryxdesign/core/i18n";
import { Theme, type ThemeMode } from "@astryxdesign/core/theme";
import { useLocale } from "next-intl";
import { createContext, use, useMemo, useState } from "react";
import { ASTRYX_MESSAGES } from "@/components/providers/astryx-provider";
import { NonceProvider } from "@/components/providers/nonce";
import { eneoTheme } from "@/theme/eneo";

type EmbedSchemeValue = {
  /** The scheme in effect: pinned by the widget, or the host page's. */
  mode: ThemeMode;
  setMode: (mode: ThemeMode) => void;
};

const EmbedSchemeContext = createContext<EmbedSchemeValue | null>(null);

/**
 * The embed page's root providers: the Eneo theme in the scheme the proxy
 * decided (the root <Theme> writes `data-theme` on <html>, which Astryx's
 * reset maps to `color-scheme`, so every token follows), Astryx's own
 * strings in the widget's language, and the CSP nonce. The host page can
 * change the scheme later (the loader's `theme` message): the chat sets it
 * through this context.
 */
export function EmbedProviders({
  nonce,
  scheme,
  children
}: {
  nonce: string | undefined;
  scheme: ThemeMode;
  children: React.ReactNode;
}) {
  const locale = useLocale();
  const [mode, setMode] = useState<ThemeMode>(scheme);
  const value = useMemo(() => ({ mode, setMode }), [mode]);
  return (
    <NonceProvider nonce={nonce}>
      <Theme theme={eneoTheme} mode={mode}>
        <InternationalizationProvider locale={locale} messages={ASTRYX_MESSAGES}>
          <EmbedSchemeContext value={value}>{children}</EmbedSchemeContext>
        </InternationalizationProvider>
      </Theme>
    </NonceProvider>
  );
}

export function useEmbedScheme(): EmbedSchemeValue {
  const value = use(EmbedSchemeContext);
  if (!value) throw new Error("useEmbedScheme needs EmbedProviders");
  return value;
}
