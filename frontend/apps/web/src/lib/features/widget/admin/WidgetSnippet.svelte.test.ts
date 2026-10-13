import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import type { Widget } from "@eneo/eneo-js";
import { describe, expect, test, vi } from "vitest";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, (params?: Record<string, string>) => string>>(
    {},
    {
      get: (_target, key) => (params?: Record<string, string>) =>
        params ? `${String(key)}(${Object.values(params).join("|")})` : String(key)
    }
  )
}));
vi.mock("$lib/paraglide/runtime", () => ({ getLocale: () => "sv" }));

import WidgetSnippet from "./WidgetSnippet.svelte";

const widget = { public_id: "wgt_test", status: "active", language: "sv" } as unknown as Widget;
const origin = "https://eneo.kommun.se";

const copyButtons = () => page.getByRole("button", { name: "widget_admin_copy" });

describe("WidgetSnippet", () => {
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
