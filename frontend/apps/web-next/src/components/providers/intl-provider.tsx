"use client";

import { createContext, use, useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { IntlProvider, type AbstractIntlMessages } from "use-intl";
import { loadMessages, LOCALE_COOKIE, type Locale } from "@/lib/i18n/locales";

const LocaleSwitchContext = createContext<((locale: Locale) => Promise<void>) | null>(null);
const subscribe = () => () => {};
const viewerTimeZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone;
const serverTimeZone = () => "Europe/Stockholm";

/** Owns the UI locale and viewer's zone; calendar dates and backend day aggregates keep their semantics. */
export function AppIntlProvider({
  locale,
  messages,
  children
}: {
  locale: string;
  messages: AbstractIntlMessages;
  children: React.ReactNode;
}) {
  const [catalog, setCatalog] = useState({ locale, messages });
  const timeZone = useSyncExternalStore(subscribe, viewerTimeZone, serverTimeZone);
  const changeLocale = useCallback(async (next: Locale) => {
    // Keep the current language and preference if its replacement cannot load.
    const messages = await loadMessages(next);
    document.cookie = `${LOCALE_COOKIE}=${next}; Path=/; Max-Age=31536000; SameSite=Lax${
      window.location.protocol === "https:" ? "; Secure" : ""
    }`;
    setCatalog({ locale: next, messages });
  }, []);

  useEffect(() => {
    document.documentElement.lang = catalog.locale;
  }, [catalog.locale]);

  return (
    <LocaleSwitchContext value={changeLocale}>
      <IntlProvider locale={catalog.locale} messages={catalog.messages} timeZone={timeZone}>
        {children}
      </IntlProvider>
    </LocaleSwitchContext>
  );
}

export function useSetLocale() {
  const changeLocale = use(LocaleSwitchContext);
  if (!changeLocale) throw new Error("useSetLocale requires AppIntlProvider");
  return changeLocale;
}
