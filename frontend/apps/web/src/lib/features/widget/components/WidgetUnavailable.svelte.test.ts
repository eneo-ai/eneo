import { page, userEvent } from "vitest/browser";
import { render } from "vitest-browser-svelte";
import { describe, expect, test, vi } from "vitest";
import axe from "axe-core";
import { virtual } from "@guidepup/virtual-screen-reader";
import "../../../../app.css";
import { BRIDGE_NAMESPACE, BRIDGE_VERSION } from "@eneo/eneo-js/widgets/embed-bridge";
import WidgetUnavailable from "./WidgetUnavailable.svelte";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, () => string>>({}, { get: (_target, key) => () => String(key) })
}));

// Test files have separate frames but share the runner's parent Window. Observe
// this frame's real messages instead of spying on that shared Window's method.
const HOST_ORIGIN = window.location.origin;

/** What the loader sends when the visitor opens the panel. */
function openPanel() {
  window.dispatchEvent(
    new MessageEvent("message", {
      origin: HOST_ORIGIN,
      source: window.parent,
      data: { ns: BRIDGE_NAMESPACE, v: 1, type: "open" }
    })
  );
}

describe("WidgetUnavailable", () => {
  test("reports ready, takes focus on open and closes from its button or Escape", async () => {
    const posted: string[] = [];
    function capture(event: MessageEvent<unknown>) {
      const data = event.data;
      if (
        event.source !== window ||
        event.origin !== HOST_ORIGIN ||
        !data ||
        typeof data !== "object" ||
        !("ns" in data) ||
        data.ns !== BRIDGE_NAMESPACE ||
        !("v" in data) ||
        data.v !== BRIDGE_VERSION ||
        !("type" in data) ||
        typeof data.type !== "string"
      )
        return;
      posted.push(data.type);
    }
    window.parent.addEventListener("message", capture);
    try {
      render(WidgetUnavailable, { hostOrigin: HOST_ORIGIN });
      await vi.waitFor(() => expect(posted).toEqual(["ready"]));

      openPanel();
      await expect
        .element(page.getByRole("heading", { name: "widget_not_available_title" }))
        .toHaveFocus();

      await userEvent.click(page.getByRole("button", { name: "widget_close" }));
      await vi.waitFor(() => expect(posted).toEqual(["ready", "close"]));

      await userEvent.keyboard("{Escape}");
      await vi.waitFor(() => expect(posted).toEqual(["ready", "close", "close"]));
    } finally {
      window.parent.removeEventListener("message", capture);
    }
  });

  test("offers no close button on the stand-alone page", async () => {
    render(WidgetUnavailable, { hostOrigin: null });
    await expect.element(page.getByText("widget_not_available_body")).toBeVisible();
    expect(page.getByRole("button").elements()).toHaveLength(0);
  });
});

describe("WidgetUnavailable for screen reader users", () => {
  test("reads the notice as soon as the panel opens", async () => {
    render(WidgetUnavailable, { hostOrigin: HOST_ORIGIN });
    await expect.element(page.getByText("widget_not_available_body")).toBeVisible();
    await virtual.start({ container: document.body });
    try {
      openPanel();
      await vi.waitFor(async () =>
        expect(await virtual.spokenPhraseLog()).toContain(
          "heading, widget_not_available_title, level 1"
        )
      );
    } finally {
      await virtual.stop();
    }
  });

  test.each(["light", "dark"] as const)(
    "passes every WCAG 2.2 A and AA rule, contrast included (%s)",
    async (scheme) => {
      document.documentElement.dataset.theme = scheme;
      render(WidgetUnavailable, { hostOrigin: HOST_ORIGIN });
      await expect.element(page.getByText("widget_not_available_body")).toBeVisible();
      const result = await axe.run(document, {
        runOnly: {
          type: "tag",
          values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"]
        }
      });
      expect(result.violations.map((v) => v.id)).toEqual([]);
      delete document.documentElement.dataset.theme;
    }
  );
});
