// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { router } from "@/test/navigation";
import { renderInApp, testAppContext } from "@/test/render";
import { ProfileMenu, profileDisplayName, profileInitials } from "./profile-menu";

vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("@/lib/i18n/actions", () => ({ setLocale: vi.fn() }));
vi.mock("@/features/whats-new/whats-new-provider", () => ({
  useWhatsNew: () => ({ enabled: true, hasUnseen: true })
}));

const TRIGGER = "Anna Lind, Sundsvalls kommun: konto och inställningar";

afterEach(cleanup);

async function openMenu(accessibilityStatement: string | null = null) {
  renderInApp(<ProfileMenu />, {
    appContext: testAppContext({ links: { accessibilityStatement } })
  });
  const trigger = screen.getByRole("button", { name: TRIGGER });
  expect(trigger.getAttribute("aria-haspopup")).toBe("menu");
  fireEvent.click(trigger);
  await screen.findByRole("menuitem", { name: "Mitt konto" });
  return trigger;
}

describe("ProfileMenu", () => {
  it("names the button after the visible name and organisation", () => {
    renderInApp(<ProfileMenu />);
    const trigger = screen.getByRole("button", { name: TRIGGER });
    expect(trigger.textContent).toContain("Anna Lind");
    expect(trigger.textContent).toContain("Sundsvalls kommun");
  });

  it("holds the account pages, what's new, language, theme and logout", async () => {
    await openMenu();
    for (const name of ["Mitt konto", "Mina API-nycklar", "Integrationer", "Språk", "Tema"]) {
      expect(screen.getByRole("menuitem", { name: new RegExp(name) })).toBeTruthy();
    }
    expect(screen.getByRole("menuitem", { name: /Nyheter/ }).textContent).toContain(
      "Nya uppdateringar"
    );
    expect(screen.getByRole("menuitem", { name: "Logga ut" })).toBeTruthy();
    expect(screen.getByText("Frontend 0.1.0 · Backend 1.2.3")).toBeTruthy();
    await expectNoAxeViolations(document.body);
  });

  it("navigates to the account page", async () => {
    await openMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: "Mitt konto" }));
    expect(router.push).toHaveBeenCalledWith("/account");
  });

  it("links the accessibility statement when one is configured", async () => {
    await openMenu("https://example.se/tillganglighetsredogorelse");
    expect(screen.getByRole("menuitem", { name: "Tillgänglighetsredogörelse" })).toBeTruthy();
  });

  it("hides the accessibility statement link when it is not configured", async () => {
    await openMenu();
    expect(screen.queryByRole("menuitem", { name: "Tillgänglighetsredogörelse" })).toBeNull();
  });

  it("names each language in its own language", async () => {
    await openMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: /Språk/ }));
    const english = await screen.findByRole("menuitemradio", { name: "English" });
    expect(english.querySelector("[lang='en']")).toBeTruthy();
    await waitFor(() =>
      expect(
        screen.getByRole("menuitemradio", { name: "Svenska" }).getAttribute("aria-checked")
      ).toBe("true")
    );
  });
});

describe("profile helpers", () => {
  it("falls back from the username to the e-mail's local part", () => {
    expect(profileDisplayName({ username: " anna.lind ", email: "x@y.se" })).toBe("anna.lind");
    expect(profileDisplayName({ username: null, email: "anna@kommun.se" })).toBe("anna");
  });

  it("makes up to two initials from names, usernames and e-mails", () => {
    expect(profileInitials("Anna Lind")).toBe("AL");
    expect(profileInitials("anna.lind")).toBe("AL");
    expect(profileInitials("örjan_ek-berg")).toBe("ÖE");
    expect(profileInitials("anna")).toBe("A");
    expect(profileInitials("")).toBe("?");
  });
});
