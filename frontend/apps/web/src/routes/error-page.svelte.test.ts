import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { writable } from "svelte/store";
import { beforeEach, describe, expect, test, vi } from "vitest";
import "../app.css";

type PageStoreValue = { error: App.Error | null; url: URL };

const state = vi.hoisted(() => ({
  page: undefined as unknown as ReturnType<typeof writable<PageStoreValue>>,
  writeText: vi.fn<(value: string) => Promise<void>>()
}));

vi.mock("$app/stores", async () => {
  const { writable: createStore } = await import("svelte/store");
  state.page = createStore<PageStoreValue>({ error: null, url: new URL("https://eneo.test/") });
  return { page: state.page };
});

vi.mock("$app/navigation", () => ({ goto: vi.fn() }));

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, (args?: Record<string, unknown>) => string>>(
    {},
    {
      get: (_target, key) => (args?: Record<string, unknown>) =>
        args ? `${String(key)}:${Object.values(args).join(",")}` : String(key)
    }
  )
}));

vi.mock("$lib/paraglide/runtime", () => ({
  localizeHref: (href: string) => href
}));

import ErrorPage from "./+error.svelte";

const TRACE_ID = "0af7651916cd43dd8448eb211c80319c";

function showError(error: App.Error) {
  state.page.set({ error, url: new URL("https://eneo.test/spaces/space-1/chat?tab=history") });
  render(ErrorPage);
}

describe("error page", () => {
  beforeEach(async () => {
    await page.viewport(1280, 800);
    state.writeText.mockClear().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: state.writeText },
      configurable: true
    });
  });

  test("announces the failure through a heading inside an alert", async () => {
    showError({ status: 500, message: "Upstream server error", code: 0 });

    const alert = page.getByRole("alert");
    await expect.element(alert).toBeVisible();
    await expect
      .element(page.getByRole("heading", { level: 1 }))
      .toHaveTextContent("error_status_message:500,Upstream server error");
  });

  test("offers a retry that re-requests the failed url from the server", async () => {
    showError({ status: 500, message: "Upstream server error", code: 0 });

    const retry = page.getByRole("link", { name: "error_try_again" });
    await expect.element(retry).toBeVisible();
    expect(retry.element().getAttribute("href")).toBe("/spaces/space-1/chat?tab=history");
    expect(retry.element().hasAttribute("data-sveltekit-reload")).toBe(true);
    expect(retry.element().getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
  });

  test("prefers the localized message for a known backend error code", async () => {
    // 9033 is MODEL_NOT_AVAILABLE; the backend sends English, the app has a
    // translation, and the toasts already use it.
    showError({ status: 400, message: "Completion model not available", code: 9033 });

    await expect
      .element(page.getByRole("heading", { level: 1 }))
      .toHaveTextContent("error_status_message:400,eneo_error_9033");
  });

  test("shows the trace id and copies it for a support report", async () => {
    showError({ status: 404, message: "Space not found", code: 0, traceId: TRACE_ID });

    await expect.element(page.getByText(TRACE_ID)).toBeVisible();

    const copy = page.getByRole("button", { name: "copy_error_reference_id" });
    const box = copy.element().getBoundingClientRect();
    expect(box.height).toBeGreaterThanOrEqual(44);

    await copy.click();

    expect(state.writeText).toHaveBeenCalledWith(TRACE_ID);
    await expect.element(page.getByRole("status")).toHaveTextContent("copied_to_clipboard");
  });

  test("keeps a long message and the trace id inside a phone-sized screen", async () => {
    await page.viewport(375, 700);
    showError({
      status: 500,
      message: "Kunde inte hämta assistenten eftersom tjänsten inte svarade i tid",
      code: 0,
      traceId: TRACE_ID
    });

    await expect.element(page.getByText(TRACE_ID)).toBeVisible();
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(375);
  });

  test("leaves the reference id out when the failure carries no trace id", async () => {
    showError({ status: 500, message: "Upstream server error", code: 0 });

    await expect.element(page.getByRole("heading", { level: 1 })).toBeVisible();
    expect(page.getByText("error_reference_id").elements()).toHaveLength(0);
  });
});
