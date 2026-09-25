import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import type { Eneo, Widget } from "@eneo/eneo-js";
import { afterEach, describe, expect, test, vi } from "vitest";
import type { LoaderRelease } from "./snippet";

const state = vi.hoisted(() => ({
  page: {
    url: new URL("http://localhost/spaces/s1/assistants/a1/widget"),
    data: { release: null as LoaderRelease | null }
  }
}));

vi.mock("$app/state", () => ({ page: state.page }));
vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, () => string>>({}, { get: (_target, key) => () => String(key) })
}));

import WidgetLiveTest from "./WidgetLiveTest.svelte";

const widget = {
  id: "11111111-1111-4111-8111-111111111111",
  public_id: "wgt_test",
  language: "sv",
  theme: { position: "bottom-right", radius: 12, color_scheme: "auto" }
} as unknown as Widget;

const eneo = {
  widgets: { previewToken: async () => ({ token: "preview-token" }) }
} as unknown as Eneo;

/** Scripts the component adds to the head; none is fetched, each reports loaded. */
function captureScripts(): HTMLScriptElement[] {
  const scripts: HTMLScriptElement[] = [];
  const append = document.head.appendChild.bind(document.head);
  vi.spyOn(document.head, "appendChild").mockImplementation(<T extends Node>(node: T): T => {
    if (!(node instanceof HTMLScriptElement)) return append(node);
    scripts.push(node);
    queueMicrotask(() => node.onload?.(new Event("load")));
    return node;
  });
  return scripts;
}

const start = () => page.getByRole("button", { name: "widget_admin_live_test_start" });

afterEach(() => {
  vi.restoreAllMocks();
});

describe("WidgetLiveTest", () => {
  test("loads the loader from the channel this installation serves", async () => {
    state.page.data.release = { version: "2.0.0", channel: "v7", integrity: "sha384-abc" };
    const scripts = captureScripts();
    render(WidgetLiveTest, { widget, eneo });

    await start().click();

    await expect
      .element(page.getByRole("button", { name: "widget_admin_live_test_stop" }))
      .toBeVisible();
    expect(scripts.map((script) => script.src)).toEqual(["http://localhost/widget/v7/eneo.js"]);
    expect(page.getByText("widget_admin_snippet_not_built").elements()).toHaveLength(0);
  });

  test("says why it cannot start when the installation has no loader", async () => {
    state.page.data.release = null;
    const scripts = captureScripts();
    render(WidgetLiveTest, { widget, eneo });

    await expect.element(page.getByText("widget_admin_snippet_not_built")).toBeVisible();
    await expect.element(start()).toBeDisabled();
    expect(scripts).toHaveLength(0);
  });
});
