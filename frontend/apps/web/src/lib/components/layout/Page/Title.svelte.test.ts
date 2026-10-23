import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, it } from "vitest";
import "../../../../app.css";
import { m } from "$lib/paraglide/messages";
import { expectNoAxeViolations } from "$lib/test/axe";
import Title from "./Title.svelte";

describe("Page.Title", () => {
  it("renders every parent as a breadcrumb link ahead of the title", async () => {
    render(Title, {
      title: "Protokoll 2026",
      parents: [
        { title: "Integrations", href: "/spaces/s1/knowledge?tab=integrations" },
        { title: "Kommunstyrelsen", href: "/spaces/s1/knowledge/integrations/wrapper/w1" }
      ]
    });

    const nav = page.getByRole("navigation", { name: m.breadcrumb() });
    await expect.element(nav).toBeVisible();
    const links = nav.getByRole("link").elements();
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/spaces/s1/knowledge?tab=integrations",
      "/spaces/s1/knowledge/integrations/wrapper/w1"
    ]);
    expect(links.map((link) => link.textContent?.trim())).toEqual([
      "← Integrations",
      "Kommunstyrelsen"
    ]);
    const separators = nav.element().querySelectorAll('[aria-hidden="true"]');
    expect(separators).toHaveLength(1);
    await expect
      .element(page.getByRole("heading", { level: 1 }))
      .toHaveTextContent("Protokoll 2026");
    // The heading fades in; the breadcrumb is what this test owns.
    await expectNoAxeViolations(nav.element());
  });

  it("keeps every crumb a visible, focusable link when the title overflows", async () => {
    const long = "Kommunstyrelsens arbetsutskott för digitalisering och verksamhetsutveckling";
    render(Title, {
      title: `${long} ${long}`,
      truncate: true,
      parents: [
        { title: long, href: "/spaces/s1/knowledge?tab=integrations" },
        { title: `${long} protokoll`, href: "/spaces/s1/knowledge/integrations/wrapper/w1" }
      ]
    });

    const nav = page.getByRole("navigation", { name: m.breadcrumb() });
    const [first, second] = nav.getByRole("link").elements() as HTMLElement[];
    // The crumb text goes screen-reader-only once the measured width overflows.
    await expect.poll(() => second.querySelector(".sr-only") !== null).toBe(true);

    expect(second.closest("li")?.classList.contains("sr-only")).toBe(false);
    expect(second.getBoundingClientRect().width).toBeGreaterThan(4);
    expect(first.getBoundingClientRect().width).toBeGreaterThan(4);
    await expect.element(nav.getByRole("link", { name: `${long} protokoll` })).toBeVisible();
    second.focus();
    expect(document.activeElement).toBe(second);
    await expectNoAxeViolations(nav.element());
  });

  it("keeps a single parent working", async () => {
    render(Title, { title: "Edit", parent: { title: "Templates", href: "/admin/templates" } });

    const links = page.getByRole("navigation", { name: m.breadcrumb() }).getByRole("link");
    expect(links.elements()).toHaveLength(1);
    await expect.element(links).toHaveAttribute("href", "/admin/templates");
  });

  it("renders no navigation without parents", async () => {
    render(Title, { title: "Settings" });
    expect(page.getByRole("navigation").elements()).toHaveLength(0);
  });
});
