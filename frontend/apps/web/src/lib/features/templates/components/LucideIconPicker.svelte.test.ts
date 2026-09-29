import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { House, Rocket } from "@lucide/svelte";
import { m } from "$lib/paraglide/messages";
import { createLucideRegistry, loadLucideIcons } from "../lucideIcons";
import LucideIconPicker from "./LucideIconPicker.svelte";

vi.mock("../lucideIcons", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lucideIcons")>()),
  loadLucideIcons: vi.fn()
}));

const registry = createLucideRegistry({ icons: { Rocket } } as never);
const rocketIcon = () => document.querySelector("svg.lucide-rocket");

beforeEach(() => {
  vi.mocked(loadLucideIcons)
    .mockReset()
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValue(registry);
});

describe("LucideIconPicker", () => {
  it("downloads the icons again when the dialog opens after a failed load", async () => {
    render(LucideIconPicker, { value: "rocket", compact: true });

    // The selected value asked for the registry once; that download failed.
    await vi.waitFor(() => expect(loadLucideIcons).toHaveBeenCalledTimes(1));
    expect(rocketIcon()).toBeNull();

    await page.getByRole("button", { name: m.change_icon_current({ iconName: "rocket" }) }).click();

    await vi.waitFor(() => expect(rocketIcon()).not.toBeNull());
    expect(loadLucideIcons).toHaveBeenCalledTimes(2);
    expect(page.getByRole("alert").elements()).toHaveLength(0);
  });

  it("shows the error in the dialog and recovers through Retry", async () => {
    render(LucideIconPicker, { compact: true });

    await page.getByRole("button", { name: m.choose_template_icon() }).click();

    await expect.element(page.getByRole("alert")).toHaveTextContent(m.icon_picker_load_error());
    expect(rocketIcon()).toBeNull();

    await page.getByRole("button", { name: m.retry() }).click();

    await vi.waitFor(() => expect(rocketIcon()).not.toBeNull());
    expect(loadLucideIcons).toHaveBeenCalledTimes(2);
    expect(page.getByRole("alert").elements()).toHaveLength(0);
  });

  it("shows an icon saved under a name Lucide has since renamed", async () => {
    vi.mocked(loadLucideIcons)
      .mockReset()
      .mockResolvedValue(createLucideRegistry({ icons: { House }, Home: House } as never));
    render(LucideIconPicker, { value: "home", compact: true });

    await vi.waitFor(() => expect(document.querySelector("svg.lucide-house")).not.toBeNull());
    await page.getByRole("button", { name: m.change_icon_current({ iconName: "home" }) }).click();

    await expect
      .element(page.getByRole("button", { name: m.select_icon({ iconName: "house" }) }))
      .toHaveAttribute("aria-pressed", "true");
  });
});
