// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import { IntlProvider } from "use-intl";
import { afterEach, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { AccountNav } from "@/features/account/account-nav";

const pathname = vi.hoisted(() => ({ current: "/account/api-keys" }));
vi.mock("@/lib/navigation", () => ({ usePathname: () => pathname.current }));

afterEach(cleanup);

it("is a named navigation of account pages with the current one marked", async () => {
  const { container } = render(
    <IntlProvider locale="sv" messages={messages}>
      <AccountNav />
    </IntlProvider>
  );
  const nav = screen.getByRole("navigation", { name: "Kontoinställningar" });
  const links = within(nav).getAllByRole("link");
  expect(links.map((link) => link.getAttribute("href"))).toEqual([
    "/account",
    "/account/api-keys",
    "/account/integrations"
  ]);
  // Astryx tabs mark the current item with aria-current="true".
  expect(within(nav).getByRole("link", { name: "API-nycklar" }).getAttribute("aria-current")).toBe(
    "true"
  );
  await expectNoAxeViolations(container);
});

it("marks Profil on Konto's own pages, which hold what Profil holds", () => {
  pathname.current = "/account/appearance";
  render(
    <IntlProvider locale="sv" messages={messages}>
      <AccountNav />
    </IntlProvider>
  );
  expect(screen.getByRole("link", { name: "Profil" }).getAttribute("aria-current")).toBe("true");
  pathname.current = "/account/api-keys";
});
