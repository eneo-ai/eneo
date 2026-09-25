// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeAll, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { ProfileMenu } from "./profile-menu";

const appContext = vi.hoisted(() => ({
  links: { accessibilityStatement: null as string | null }
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("@/lib/i18n/actions", () => ({ setLocale: vi.fn() }));
vi.mock("@/features/whats-new/whats-new-provider", () => ({
  useWhatsNew: () => ({ enabled: false, hasUnseen: false })
}));
vi.mock("@/components/providers/app-context", () => ({
  useAppContext: () => ({
    user: { email: "anna@example.se" },
    federationStatus: { has_multi_tenant_federation: false },
    links: appContext.links
  })
}));

const messages = {
  account_and_settings: "Konto och inställningar",
  my_account: "Mitt konto",
  my_api_keys: "Mina API-nycklar",
  integrations: "Integrationer",
  language: "Språk",
  logout: "Logga ut",
  a11y_statement_link: "Tillgänglighetsredogörelse"
};

beforeAll(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  );
});

afterEach(() => {
  cleanup();
  appContext.links.accessibilityStatement = null;
});

async function openMenu() {
  render(
    <NextIntlClientProvider locale="sv" messages={messages}>
      <ProfileMenu />
    </NextIntlClientProvider>
  );
  fireEvent.keyDown(screen.getByRole("button", { name: "Konto och inställningar" }), {
    key: "Enter"
  });
  await screen.findByRole("menuitem", { name: /mitt konto/i });
}

it("links the accessibility statement when one is configured", async () => {
  appContext.links.accessibilityStatement = "https://example.se/tillganglighetsredogorelse";
  await openMenu();
  const link = screen.getByRole("menuitem", { name: "Tillgänglighetsredogörelse" });
  expect(link.getAttribute("href")).toBe("https://example.se/tillganglighetsredogorelse");
  await expectNoAxeViolations(document.body);
});

it("hides the accessibility statement link when it is not configured", async () => {
  await openMenu();
  expect(screen.queryByRole("menuitem", { name: "Tillgänglighetsredogörelse" })).toBeNull();
});
