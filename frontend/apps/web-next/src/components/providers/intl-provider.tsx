"use client";

import { useSyncExternalStore } from "react";
import { IntlProvider, type AbstractIntlMessages } from "use-intl";

const subscribe = () => () => {};
const viewerTimeZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone;
const serverTimeZone = () => "Europe/Stockholm";

/** Owns the UI timestamp zone. The document boot supplies its locale and catalogue. */
export function AppIntlProvider({
  locale,
  messages,
  children
}: {
  locale: string;
  messages: AbstractIntlMessages;
  children: React.ReactNode;
}) {
  const timeZone = useSyncExternalStore(subscribe, viewerTimeZone, serverTimeZone);

  return (
    <IntlProvider locale={locale} messages={messages} timeZone={timeZone}>
      {children}
    </IntlProvider>
  );
}
