// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { ThemeProvider } from "next-themes";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
import { AccountHome } from "./account-home.client";

vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("@/lib/i18n/actions", () => ({ setLocale: vi.fn() }));
const whatsNew = vi.hoisted(() => ({ enabled: true, hasUnseen: true }));
vi.mock("@/features/whats-new/whats-new-provider", () => ({ useWhatsNew: () => whatsNew }));
const navigateTo = vi.hoisted(() => vi.fn());
vi.mock("@/lib/navigate-to", () => ({ navigateTo }));

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  whatsNew.enabled = true;
  whatsNew.hasUnseen = true;
});

function renderHome(appContext = testAppContext()) {
  return renderInApp(
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
      <AccountHome />
    </ThemeProvider>,
    { appContext }
  );
}

const row = (name: RegExp | string) => screen.getByRole("link", { name });

describe("Konto on a phone (decision 22)", () => {
  it("is one page: who you are, the settings in groups, Logga ut last", async () => {
    setViewport("phone");
    const { container } = renderHome();

    expect(screen.getByRole("heading", { level: 1, name: "Konto" })).toBeTruthy();
    expect(screen.getByText("Anna Lind")).toBeTruthy();
    expect(screen.getByText("anna.lind@example.se")).toBeTruthy();
    expect(screen.getByText("Sundsvalls kommun · Medarbetare")).toBeTruthy();
    expect(
      screen.getAllByRole("heading", { level: 2 }).map((heading) => heading.textContent)
    ).toEqual(["Inställningar", "Säkerhet och åtkomst", "Eneo"]);

    // Each row is a link with what it holds now in its name.
    expect(row(/^Utseende och språk ?, System · Svenska$/).getAttribute("href")).toBe(
      "/account/appearance"
    );
    expect(row(/^Kopieringsformat ?, Markdown$/).getAttribute("href")).toBe("/account/copy-format");
    expect(row("Byt lösenord").getAttribute("href")).toBe("/account/password");
    // What's new's "Visa mig" finds both here (packages/whats-new).
    expect(row("Byt lösenord").dataset.tour).toBe("account-password");
    expect(row(/^Kopieringsformat/).dataset.tour).toBe("account-copy-format");
    expect(row("Mina API-nycklar").getAttribute("href")).toBe("/account/api-keys");
    expect(row("Integrationer").getAttribute("href")).toBe("/account/integrations");
    expect(row(/^Nyheter ?, Nya uppdateringar$/).getAttribute("href")).toBe("/whats-new");
    // Administration is for admins.
    expect(screen.queryByRole("link", { name: "Administration" })).toBeNull();

    const logout = screen.getByRole("button", { name: "Logga ut" });
    const controls = [...container.querySelectorAll("a[href], button")];
    expect(controls.at(-1)).toBe(logout);
    expect(screen.getByText("Frontend 0.1.0 · Backend 1.2.3")).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("logs out with a full page load, not a client navigation", () => {
    setViewport("phone");
    renderHome();
    fireEvent.click(screen.getByRole("button", { name: "Logga ut" }));
    expect(navigateTo).toHaveBeenCalledWith("/logout");
  });

  it("shows Administration to admins, and Nyheter only as the tenant has it", () => {
    setViewport("phone");
    whatsNew.hasUnseen = false;
    renderHome(testAppContext({ permissions: ["admin"] }));
    expect(row("Administration").getAttribute("href")).toBe("/admin");
    expect(row("Nyheter")).toBeTruthy();
    cleanup();

    whatsNew.enabled = false;
    renderHome();
    expect(screen.queryByRole("link", { name: /Nyheter/ })).toBeNull();
    // Nothing in Eneo applies, so the group is not there either.
    expect(screen.queryByRole("heading", { level: 2, name: "Eneo" })).toBeNull();
  });

  it("keeps the accessibility statement, the old app and the organisation switch where configured", () => {
    setViewport("phone");
    renderHome(
      testAppContext({
        links: {
          accessibilityStatement: "https://example.se/tillganglighet",
          legacyApp: "https://app.example.se"
        },
        federationStatus: { has_multi_tenant_federation: true }
      })
    );
    const statement = row(/^Tillgänglighetsredogörelse/);
    expect(statement.getAttribute("href")).toBe("https://example.se/tillganglighet");
    expect(statement.getAttribute("target")).toBe("_blank");
    expect(statement.textContent).toContain("(öppnas i en ny flik)");
    expect(row("Tillbaka till gamla appen").getAttribute("href")).toBe("https://app.example.se");

    fireEvent.click(screen.getByRole("button", { name: "Välj en annan organisation" }));
    expect(navigateTo).toHaveBeenCalledWith("/login/switch-organisation");
  });

  it("is the page on an iPad held upright too, where the drawer is", () => {
    setViewport("tablet-portrait");
    renderHome();
    expect(screen.getByRole("heading", { level: 1, name: "Konto" })).toBeTruthy();
    expect(screen.queryByRole("navigation", { name: "Kontoinställningar" })).toBeNull();
  });
});

describe("Konto from 1024 px", () => {
  it("keeps the profile and the password form", () => {
    setViewport("tablet-landscape");
    renderHome();
    expect(screen.queryByRole("heading", { level: 1, name: "Konto" })).toBeNull();
    const profile = screen.getByRole("heading", { name: "Profil" }).closest("section")!;
    expect(within(profile).getByRole("combobox", { name: "Språk" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Byt lösenord" })).toBeTruthy();
  });
});
