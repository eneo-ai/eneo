"use client";

import { InternationalizationProvider } from "@astryxdesign/core/i18n";
import astryxSv from "@astryxdesign/core/locales/sv-SE.json";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { useState, type ReactNode } from "react";
import { AppContextProvider, type AppContextData } from "@/components/providers/app-context";
import sv from "@/lib/i18n/messages/sv.json";

/**
 * Test-only providers for chat components: the real Swedish catalog (the
 * default locale), Astryx's Swedish strings, a retry-free query client and a
 * minimal app context. Not imported by app code.
 */
export const testAppContext = {
  user: {
    id: "user-1",
    email: "anna.lind@example.se",
    username: "Anna Lind",
    predefined_roles: [],
    roles: [],
    user_groups: []
  },
  tenant: { id: "tenant-1", name: "Sundsvalls kommun", show_model_pricing: false },
  settings: { chatbot_widget: null },
  federationStatus: { has_multi_tenant_federation: false },
  limits: { attachments: { formats: [], max_in_question: 5 } },
  featureFlags: { showWebSearch: true },
  links: { accessibilityStatement: null },
  versions: { frontend: "test", backend: "test" }
} as unknown as AppContextData;

export function ChatTestProviders({
  children,
  appContext = testAppContext
}: {
  children: ReactNode;
  appContext?: AppContextData;
}) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } }
      })
  );
  return (
    <NextIntlClientProvider locale="sv" messages={sv} timeZone="Europe/Stockholm">
      <InternationalizationProvider locale="sv" messages={{ sv: astryxSv }}>
        <QueryClientProvider client={client}>
          <AppContextProvider value={appContext}>{children}</AppContextProvider>
        </QueryClientProvider>
      </InternationalizationProvider>
    </NextIntlClientProvider>
  );
}
