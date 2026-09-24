import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { afterEach, describe, expect, test, vi } from "vitest";
import { BRIDGE_NAMESPACE } from "../embedBridge";
import WidgetUnavailable from "./WidgetUnavailable.svelte";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, () => string>>({}, { get: (_target, key) => () => String(key) })
}));

// Vitest runs the test page in a frame, so the page is "embedded" with the
// runner as its host; messages go to window.parent.
const HOST_ORIGIN = location.origin;

const posted = () =>
  vi.mocked(window.parent.postMessage).mock.calls.map((call) => (call[0] as { type: string }).type);

afterEach(() => vi.restoreAllMocks());

describe("WidgetUnavailable", () => {
  test("reports ready, takes focus on open and closes from its button or Escape", async () => {
    vi.spyOn(window.parent, "postMessage");
    render(WidgetUnavailable, { hostOrigin: HOST_ORIGIN });
    await vi.waitFor(() => expect(posted()).toContain("ready"));

    window.dispatchEvent(
      new MessageEvent("message", {
        origin: HOST_ORIGIN,
        source: window.parent,
        data: { ns: BRIDGE_NAMESPACE, v: 1, type: "open" }
      })
    );
    await expect
      .element(page.getByRole("heading", { name: "widget_not_available_title" }))
      .toHaveFocus();

    await userEvent.click(page.getByRole("button", { name: "widget_close" }));
    expect(posted()).toEqual(["ready", "close"]);

    await userEvent.keyboard("{Escape}");
    expect(posted()).toEqual(["ready", "close", "close"]);
  });

  test("offers no close button on the stand-alone page", async () => {
    render(WidgetUnavailable, { hostOrigin: null });
    await expect.element(page.getByText("widget_not_available_body")).toBeVisible();
    expect(page.getByRole("button").elements()).toHaveLength(0);
  });
});
