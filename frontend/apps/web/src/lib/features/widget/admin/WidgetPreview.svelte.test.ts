/* eslint-disable eneo/no-raw-color -- fixtures use literal widget colours */
import { render } from "vitest-browser-svelte";
import type { Eneo, Widget } from "@eneo/eneo-js";
import { describe, expect, test, vi } from "vitest";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, () => string>>({}, { get: (_target, key) => () => String(key) })
}));
const toastError = vi.hoisted(() => vi.fn());
vi.mock("$lib/core/errors", () => ({ toastError }));

import WidgetPreview from "./WidgetPreview.svelte";

type Minted = { token: string; expires_in: number };

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const widget = {
  id: "11111111-1111-4111-8111-111111111111",
  public_id: "wgt_test",
  status: "draft",
  token_generation: 1,
  show_sources: true,
  revision: 3,
  language: "sv",
  theme: { primary_color: "#1F4E79", radius: 12, color_scheme: "auto" },
  updated_at: "2026-09-21T10:00:00Z"
} as unknown as Widget;

// Every mint stays pending until the test answers it, so answers can arrive
// in any order relative to the widget's saves.
function renderPreview() {
  const mints: Array<ReturnType<typeof deferred<Minted>>> = [];
  const previewToken = vi.fn(() => {
    const next = deferred<Minted>();
    mints.push(next);
    return next.promise;
  });
  const eneo = { widgets: { previewToken } } as unknown as Eneo;
  const screen = render(WidgetPreview, { widget, eneo });
  return { screen, mints, previewToken };
}

const frameSrc = () => document.querySelector("iframe")?.getAttribute("src") ?? "";
const settle = () => new Promise((resolve) => setTimeout(resolve, 50));

describe("WidgetPreview tokens", () => {
  test("an answer minted for an earlier generation cannot replace the current token", async () => {
    const { screen, mints, previewToken } = renderPreview();
    await expect.poll(() => previewToken.mock.calls.length).toBe(1);

    // A rules save rotates the tokens while the first mint is still pending.
    await screen.rerender({ widget: { ...widget, token_generation: 2 } });
    await expect.poll(() => previewToken.mock.calls.length).toBe(2);

    mints[1].resolve({ token: "current", expires_in: 3600 });
    await expect.poll(frameSrc).toContain("preview=current");

    // The stale answer arrives last: dropped, and no further mint follows.
    mints[0].resolve({ token: "stale", expires_in: 3600 });
    await settle();
    expect(frameSrc()).toContain("preview=current");
    expect(previewToken).toHaveBeenCalledTimes(2);
  });

  test("a stale mint that fails does not fail the current preview", async () => {
    const { screen, mints, previewToken } = renderPreview();
    await expect.poll(() => previewToken.mock.calls.length).toBe(1);
    await screen.rerender({ widget: { ...widget, token_generation: 2 } });
    await expect.poll(() => previewToken.mock.calls.length).toBe(2);
    mints[1].resolve({ token: "current", expires_in: 3600 });
    await expect.poll(frameSrc).toContain("preview=current");

    mints[0].reject(new Error("token generation is stale"));
    await settle();
    expect(toastError).not.toHaveBeenCalled();
    expect(frameSrc()).toContain("preview=current");
    expect(document.querySelector("[role=alert]")).toBeNull();
  });
});
