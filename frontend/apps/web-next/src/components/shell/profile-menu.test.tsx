// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNameToHoldVisibleText, expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";
import { ProfileMenu, profileDisplayName, profileInitials } from "./profile-menu";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
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
    // The initials are not part of what the name repeats: they are drawn, not text (WCAG 2.5.3).
    expectNameToHoldVisibleText(trigger, TRIGGER);
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

  it("links each page it opens, so a modified click opens it in a new tab", async () => {
    await openMenu();
    for (const [name, href] of [
      ["Mitt konto", "/account"],
      ["Mina API-nycklar", "/account/api-keys"],
      [/Nyheter/, "/whats-new"],
      ["Integrationer", "/account/integrations"]
    ] as const) {
      const item = screen.getByRole("menuitem", { name });
      expect(item.tagName).toBe("A");
      expect(item.getAttribute("href")).toBe(href);
    }
  });

  // A link would load them in the app, and ahead of a click on hover; they need a full page load.
  it("keeps logout and the organisation switch as actions, not links", async () => {
    renderInApp(<ProfileMenu />, {
      appContext: testAppContext({ federationStatus: { has_multi_tenant_federation: true } })
    });
    fireEvent.click(screen.getByRole("button", { name: TRIGGER }));
    for (const name of ["Välj en annan organisation", "Logga ut"]) {
      expect((await screen.findByRole("menuitem", { name })).hasAttribute("href")).toBe(false);
    }
  });

  it("links the accessibility statement when one is configured", async () => {
    await openMenu("https://example.se/tillganglighetsredogorelse");
    expect(
      screen.getByRole("menuitem", { name: "Tillgänglighetsredogörelse" }).getAttribute("href")
    ).toBe("https://example.se/tillganglighetsredogorelse");
  });

  it("hides the accessibility statement link when it is not configured", async () => {
    await openMenu();
    expect(screen.queryByRole("menuitem", { name: "Tillgänglighetsredogörelse" })).toBeNull();
  });

  it("links the help centre on a page without a SideNav, in a new tab, when one is configured", async () => {
    const helpCenter = "https://example.se/hjalp";
    const { unmount } = renderInApp(<ProfileMenu inTopBar withHelpCenter />, {
      appContext: testAppContext({ links: { helpCenter } })
    });
    fireEvent.click(screen.getByRole("button", { name: TRIGGER }));
    const link = await screen.findByRole("menuitem", {
      name: "Har du en fråga? (öppnas i en ny flik)"
    });
    expect(link.getAttribute("href")).toBe(helpCenter);
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    expect(link.querySelector("svg.lucide-external-link")).toBeTruthy();
    unmount();

    renderInApp(<ProfileMenu inTopBar withHelpCenter />, {
      appContext: testAppContext({ links: { helpCenter: null } })
    });
    fireEvent.click(screen.getByRole("button", { name: TRIGGER }));
    await screen.findByRole("menuitem", { name: "Mitt konto" });
    expect(screen.queryByRole("menuitem", { name: /Har du en fråga/ })).toBeNull();
  });

  it("leaves the help centre to the SideNav's foot beside it", async () => {
    renderInApp(<ProfileMenu inTopBar />, {
      appContext: testAppContext({ links: { helpCenter: "https://example.se/hjalp" } })
    });
    fireEvent.click(screen.getByRole("button", { name: TRIGGER }));
    await screen.findByRole("menuitem", { name: "Mitt konto" });
    expect(screen.queryByRole("menuitem", { name: /Har du en fråga/ })).toBeNull();
  });

  it("offers a return to the existing app only when configured", async () => {
    renderInApp(<ProfileMenu />, {
      appContext: testAppContext({ links: { legacyApp: "https://app.example" } })
    });
    fireEvent.click(screen.getByRole("button", { name: TRIGGER }));
    expect(
      (await screen.findByRole("menuitem", { name: "Tillbaka till gamla appen" })).getAttribute(
        "href"
      )
    ).toBe("https://app.example");
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
