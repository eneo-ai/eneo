"use client";

import { useState } from "react";
import { IntlProvider, type AbstractIntlMessages } from "use-intl";

const viewerTimeZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone;

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
  const [timeZone] = useState(viewerTimeZone);

  return (
    <IntlProvider locale={locale} messages={messages} timeZone={timeZone}>
      {children}
    </IntlProvider>
  );
}
