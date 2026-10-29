import { createContext, use } from "react";
import type { AbstractIntlMessages } from "use-intl";
import type { Locale } from "@/lib/i18n/locales";

/**
 * What src/main.tsx resolves before the first render and the root route
 * (src/routes/__root.tsx) provides to the app: the locale with its
 * catalogue, and the document's CSP nonce.
 */
export type Boot = {
  locale: Locale;
  messages: AbstractIntlMessages;
  nonce: string | undefined;
};

export const BootContext = createContext<Boot | null>(null);

export function useBoot(): Boot {
  const boot = use(BootContext);
  if (!boot) throw new Error("useBoot() needs <BootContext> (src/main.tsx renders it).");
  return boot;
}
