// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { AccountNav } from "./account-nav.client";

vi.mock("next/navigation", () => ({ usePathname: () => "/account/api-keys" }));

afterEach(cleanup);

it("is a named list of account pages with the current one marked", async () => {
  const { container } = render(
    <NextIntlClientProvider locale="sv" messages={messages}>
      <AccountNav />
    </NextIntlClientProvider>
  );
  const nav = screen.getByRole("navigation", { name: "Kontoinställningar" });
  const links = within(nav).getAllByRole("link");
  expect(links.map((link) => link.getAttribute("href"))).toEqual([
    "/account",
    "/account/api-keys",
    "/account/integrations"
  ]);
  expect(within(nav).getByRole("link", { name: "API-nycklar" }).getAttribute("aria-current")).toBe(
    "page"
  );
  await expectNoAxeViolations(container);
});
