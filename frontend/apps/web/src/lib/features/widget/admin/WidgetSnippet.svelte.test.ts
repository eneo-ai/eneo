import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import type { Widget } from "@eneo/eneo-js";
import { describe, expect, test, vi } from "vitest";

const locale = vi.hoisted(() => ({ current: "sv" as "sv" | "en" }));
vi.mock("$lib/paraglide/messages", async () => {
  const { default: en } = await import("../../../../../messages/en.json");
  const { default: sv } = await import("../../../../../messages/sv.json");
  return {
    m: new Proxy<Record<string, (params?: Record<string, string>) => string>>(
      {},
      {
        get: (_target, key) => (params?: Record<string, string>) =>
          key === "widget_admin_snippet_pinned_help"
            ? { en, sv }[locale.current].widget_admin_snippet_pinned_help
            : params
              ? `${String(key)}(${Object.values(params).join("|")})`
              : String(key)
      }
    )
  };
});
vi.mock("$lib/paraglide/runtime", () => ({ getLocale: () => locale.current }));

import WidgetSnippet from "./WidgetSnippet.svelte";

const widget = { public_id: "wgt_test", status: "active", language: "sv" } as unknown as Widget;
const origin = "https://eneo.kommun.se";

const copyButtons = () => page.getByRole("button", { name: "widget_admin_copy" });

describe("WidgetSnippet", () => {
  test.each([
    ["en", "Pinned versions keep working when a newer loader is released."],
    ["sv", "Låsta versioner fortsätter att fungera när en ny version av laddarskriptet släpps."]
  ] as const)("pinned help in %s explains that upgrades are optional", async (language, help) => {
    locale.current = language;
    render(WidgetSnippet, {
      widget,
      origin,
      release: { version: "1.0.3", channel: "v1", integrity: "sha384-old" }
    });
    await page.getByRole("switch", { name: "widget_admin_snippet_pinned" }).click();
    await expect.element(page.getByText(help, { exact: false })).toBeVisible();
    await expect
      .element(page.getByRole("region", { name: "widget_admin_snippet", exact: true }))
      .toHaveTextContent('/widget/1.0.3/eneo.js"');
    await expect
      .element(page.getByRole("region", { name: "widget_admin_snippet", exact: true }))
      .toHaveTextContent('integrity="sha384-old"');
  });

  test("gives the floating snippet of the channel this installation serves", async () => {
    render(WidgetSnippet, {
      widget,
      origin,
      release: { version: "2.0.0", channel: "v1", integrity: "sha384-abc" }
    });

    await expect
      .element(
        page.getByText(
          '<script async src="https://eneo.kommun.se/widget/v1/eneo.js" data-widget-id="wgt_test"></script>'
        )
      )
      .toBeVisible();
    await expect.element(copyButtons().first()).toBeEnabled();
    expect(page.getByText("widget_admin_snippet_not_built").elements()).toHaveLength(0);
  });

  test("warns instead of offering a snippet when the loader is not built", async () => {
    render(WidgetSnippet, { widget, origin, release: null });

    await expect.element(page.getByText("widget_admin_snippet_not_built")).toBeVisible();
    expect(document.body.textContent).not.toContain("<script");
    await expect.element(copyButtons().first()).toBeDisabled();
    // The stand-alone page needs no loader and stays copyable.
    await expect.element(copyButtons().last()).toBeEnabled();
  });
});
