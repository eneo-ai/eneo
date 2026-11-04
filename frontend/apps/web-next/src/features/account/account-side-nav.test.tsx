// @vitest-environment jsdom
import { SideNav } from "@astryxdesign/core/SideNav";
import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { setRoute } from "@/test/navigation";
import { renderInApp } from "@/test/render";
import { AccountNavHeading, AccountNavSections } from "./account-side-nav";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
const whatsNew = vi.hoisted(() => ({ enabled: true, hasUnseen: true }));
vi.mock("@/features/whats-new/whats-new-provider", () => ({ useWhatsNew: () => whatsNew }));

function renderNav(route: string) {
  setRoute(route);
  return renderInApp(
    <SideNav aria-label="Konto och inställningar" header={<AccountNavHeading />}>
      <AccountNavSections />
    </SideNav>
  );
}

const links = () =>
  screen
    .getAllByRole("link")
    .map((link) => [link.getAttribute("href"), link.getAttribute("aria-current") === "page"]);

afterEach(() => {
  cleanup();
  whatsNew.enabled = true;
});

describe("account sidebar", () => {
  it("lists Svelte's account pages and marks the profile pages as Mitt konto", () => {
    renderNav("/account/password");
    expect(links()).toEqual([
      ["/account", true],
      ["/account/integrations", false],
      ["/account/api-keys", false],
      ["/whats-new", false]
    ]);
    expect(screen.getByText("Nya uppdateringar")).toBeTruthy();
  });

  it("marks Nyheter on the release notes, and hides it when they are off", () => {
    renderNav("/whats-new");
    expect(links().at(-1)).toEqual(["/whats-new", true]);
    cleanup();
    whatsNew.enabled = false;
    renderNav("/account");
    expect(links().map(([href]) => href)).not.toContain("/whats-new");
  });

  it("has no axe violations", async () => {
    const { container } = renderNav("/account/api-keys");
    await expectNoAxeViolations(container);
  });
});
