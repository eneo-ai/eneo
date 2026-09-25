import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { AstryxProvider } from "@/components/providers/astryx-provider";
import messages from "@/lib/i18n/messages/sv.json";

/**
 * Test-only: renders UI inside the app's providers, in Swedish: React Query,
 * next-intl with the real catalog and the Astryx provider (its Swedish strings
 * and next/link), so tests query what users actually see and hear.
 */
export function renderInApp(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="sv" messages={messages} timeZone="Europe/Stockholm">
        <AstryxProvider>{ui}</AstryxProvider>
      </NextIntlClientProvider>
    </QueryClientProvider>
  );
}
