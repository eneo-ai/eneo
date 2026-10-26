import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  CreditCard,
  Database,
  House,
  Image,
  Navigation,
  Package,
  Rocket,
  Tag,
  type IconNode
} from "@lucide/svelte";
import type { Component } from "svelte";
import { loadLucideIconOrNull } from "../lucideIcons";
import TemplateIcon from "./TemplateIcon.svelte";

vi.mock("../lucideIcons", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lucideIcons")>()),
  loadLucideIconOrNull: vi.fn()
}));

const template = { name: "Budget helper", category: "finance", icon_name: "rocket" };
const initial = () => document.body.textContent?.trim();
// Svelte's empty comment anchors are not drawn, and Lucide's Icon has one more.
const svgIn = (container: HTMLElement) =>
  container.querySelector("svg")?.outerHTML.replaceAll("<!---->", "");

beforeEach(() => {
  vi.mocked(loadLucideIconOrNull).mockReset();
});

describe("TemplateIcon", () => {
  it("shows the initial when the icon cannot be loaded", async () => {
    vi.mocked(loadLucideIconOrNull).mockResolvedValue(null);

    render(TemplateIcon, { template });

    await vi.waitFor(() => expect(initial()).toBe("B"));
    expect(document.querySelector("svg")).toBeNull();
  });

  it("shows the icon, and no initial, once it arrives", async () => {
    const iconNode: IconNode = [["path", { d: "M4 4h16v16H4z" }]];
    vi.mocked(loadLucideIconOrNull).mockResolvedValue({ name: "rocket", iconNode });

    render(TemplateIcon, { template });

    await vi.waitFor(() => expect(document.querySelector("svg.lucide-rocket")).not.toBeNull());
    expect(initial()).toBe("");
  });

  it("shows the initial right away when the template has no icon", async () => {
    vi.mocked(loadLucideIconOrNull).mockResolvedValue(null);

    render(TemplateIcon, { template: { ...template, icon_name: null } });

    expect(initial()).toBe("B");
  });

  it("draws the same SVG as Lucide's own component for the icon", async () => {
    const actual = await vi.importActual<typeof import("../lucideIcons")>("../lucideIcons");
    vi.mocked(loadLucideIconOrNull).mockImplementation(actual.loadLucideIconOrNull);
    // The first download of the whole set can outlast vi.waitFor on a busy machine.
    await actual.loadLucideIcons();
    // Every SVG element type Lucide uses, an icon with a fill, and a renamed one.
    const cases: [string, Component<{ class?: string }>, "medium" | "large"][] = [
      ["rocket", Rocket, "medium"],
      ["image", Image, "large"],
      ["credit-card", CreditCard, "medium"],
      ["database", Database, "medium"],
      ["package", Package, "medium"],
      ["navigation", Navigation, "medium"],
      ["tag", Tag, "medium"],
      ["home", House, "large"]
    ];

    for (const [icon_name, Lucide, size] of cases) {
      const drawn = render(TemplateIcon, { template: { ...template, icon_name }, size });
      const expected = render(Lucide, {
        class: `text-dynamic-stronger ${size === "large" ? "h-5 w-5" : "h-4 w-4"}`
      });
      await vi.waitFor(() => expect(drawn.container.querySelector("svg")).not.toBeNull());

      expect(svgIn(drawn.container)).toBe(svgIn(expected.container));
    }
  });
});
