// @vitest-environment jsdom
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import type { Widget } from "./autosave";

const api = vi.hoisted(() => ({ POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { WidgetLiveTest } from "./widget-live-test";

const PAUSED = "Testa i Eneo är inte tillgängligt medan widgeten är pausad.";

const widget = {
  id: "w1",
  public_id: "wgt_aaaaaaaaaaaaaaaaaaaaaa",
  status: "paused",
  language: "sv",
  theme: { position: "bottom-right", radius: 12, color_scheme: "auto" }
} as unknown as Widget;

/** The text of the elements an element's aria-describedby points at. */
function descriptionOf(element: Element) {
  return (element.getAttribute("aria-describedby") ?? "")
    .split(" ")
    .filter(Boolean)
    .map((id) => document.getElementById(id)?.textContent ?? "")
    .join(" ");
}

afterEach(() => api.POST.mockReset());

describe("WidgetLiveTest of a paused widget", () => {
  it("cannot start, says why, and asks for no token", () => {
    renderInApp(
      <WidgetLiveTest
        widget={widget}
        release={{ version: "1.0.11", channel: "v1", integrity: "sha384-x" }}
      />
    );
    const start = screen.getByRole("button", { name: "Visa widgeten på den här sidan" });
    expect(start.hasAttribute("disabled")).toBe(true);
    expect(descriptionOf(start)).toBe(PAUSED);

    fireEvent.click(start);
    expect(api.POST).not.toHaveBeenCalled();
    expect(document.querySelector("eneo-widget")).toBeNull();
  });
});

describe("WidgetLiveTest of a live widget", () => {
  it("ends a running test once the widget is paused", async () => {
    // The loader is already on the page, so the test mounts at once.
    if (!customElements.get("eneo-widget")) {
      customElements.define("eneo-widget", class extends HTMLElement {});
    }
    api.POST.mockResolvedValue({
      data: { token: "preview-token", expires_in: 900, public_id: widget.public_id },
      response: new Response(null, { status: 200 })
    });
    const release = { version: "1.0.11", channel: "v1", integrity: "sha384-x" };
    const live = { ...widget, status: "active" } as Widget;
    const { rerender } = renderInApp(<WidgetLiveTest widget={live} release={release} />);

    fireEvent.click(screen.getByRole("button", { name: "Visa widgeten på den här sidan" }));
    await screen.findByRole("button", { name: "Ta bort widgeten från den här sidan" });
    expect(document.querySelectorAll("eneo-widget")).toHaveLength(1);

    // The pause invalidated the token the mounted widget was given.
    rerender(<WidgetLiveTest widget={{ ...live, status: "paused" } as Widget} release={release} />);

    await waitFor(() => expect(document.querySelectorAll("eneo-widget")).toHaveLength(0));
    const start = screen.getByRole("button", { name: "Visa widgeten på den här sidan" });
    expect(descriptionOf(start)).toBe(PAUSED);
  });
});
