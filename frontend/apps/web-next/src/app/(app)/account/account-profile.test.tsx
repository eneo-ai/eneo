// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { AccountProfile } from "./account-profile.client";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("@/lib/i18n/actions", () => ({ setLocale: vi.fn() }));
vi.mock("@/components/providers/app-context", () => ({
  useAppContext: () => ({
    settings: {},
    user: { email: "anna@example.se", roles: [] },
    tenant: { name: "Sundsvall" },
    versions: { frontend: "0.1.0", backend: "2.3.0" }
  })
}));

afterEach(cleanup);

it("names the language picker by its row title (a combobox takes no name from its value)", () => {
  render(
    <NextIntlClientProvider locale="sv" messages={messages}>
      <AccountProfile />
    </NextIntlClientProvider>
  );

  expect(screen.getByRole("combobox", { name: "Språk" })).toBeTruthy();
});

it("shows the frontend's and the backend's version", () => {
  render(
    <NextIntlClientProvider locale="sv" messages={messages}>
      <AccountProfile />
    </NextIntlClientProvider>
  );

  expect(screen.getByText("Frontend 0.1.0 · Backend 2.3.0")).toBeTruthy();
});
