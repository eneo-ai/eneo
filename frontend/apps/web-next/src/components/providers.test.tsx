// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { Providers } from "./providers";

afterEach(() => {
  vi.unstubAllGlobals();
});

it("reloads the app when another tab signs in or out", async () => {
  const reload = vi.fn();
  vi.stubGlobal("location", { ...window.location, reload });
  render(
    <NextIntlClientProvider locale="sv" messages={messages}>
      <Providers nonce={undefined}>
        <p>Eneo</p>
      </Providers>
    </NextIntlClientProvider>
  );

  // Another tab: its own document, so its own instance of the module.
  vi.resetModules();
  const otherTab = await import("@/lib/session/identity-broadcast");
  otherTab.announceIdentityChange();

  await vi.waitFor(() => expect(reload).toHaveBeenCalledOnce());
});
