import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Rocket } from "lucide-svelte";
import { loadLucideIconOrNull, type LucideIconComponent } from "../lucideIcons";
import TemplateIcon from "./TemplateIcon.svelte";

vi.mock("../lucideIcons", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lucideIcons")>()),
  loadLucideIconOrNull: vi.fn()
}));

const template = { name: "Budget helper", category: "finance", icon_name: "rocket" };
const initial = () => document.body.textContent?.trim();

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
    vi.mocked(loadLucideIconOrNull).mockResolvedValue(Rocket as unknown as LucideIconComponent);

    render(TemplateIcon, { template });

    await vi.waitFor(() => expect(document.querySelector("svg.lucide-rocket")).not.toBeNull());
    expect(initial()).toBe("");
  });

  it("shows the initial right away when the template has no icon", async () => {
    vi.mocked(loadLucideIconOrNull).mockResolvedValue(null);

    render(TemplateIcon, { template: { ...template, icon_name: null } });

    expect(initial()).toBe("B");
  });
});
