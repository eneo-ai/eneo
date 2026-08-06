import { render } from "svelte/server";
import { writable } from "svelte/store";
import { describe, expect, test, vi } from "vitest";

type PageStoreValue = { error: App.Error | null; url: URL };

const FAILED_URL = new URL("https://eneo.test/spaces/space-1/chat");

const state = vi.hoisted(() => ({
  page: undefined as unknown as ReturnType<typeof writable<PageStoreValue>>
}));

vi.mock("$app/stores", async () => {
  const { writable: createStore } = await import("svelte/store");
  // Inline: `vi.mock` factories are hoisted above module-level constants.
  state.page = createStore<PageStoreValue>({
    error: null,
    url: new URL("https://eneo.test/spaces/space-1/chat")
  });
  return { page: state.page };
});

vi.mock("$app/navigation", () => ({ goto: vi.fn() }));

import ErrorPage from "./+error.svelte";

const TRACE_ID = "0af7651916cd43dd8448eb211c80319c";

describe("error page on the server", () => {
  test("renders the failure and its trace id without client-side JavaScript", () => {
    // The error page is what a broken deploy shows; it cannot depend on the
    // bundle that may be the thing failing to load.
    state.page.set({
      error: { status: 500, message: "Upstream server error", code: 0, traceId: TRACE_ID },
      url: FAILED_URL
    });

    const { body, head } = render(ErrorPage);

    expect(body).toContain("Upstream server error");
    expect(body).toContain(TRACE_ID);
    expect(body).toContain('role="alert"');
    expect(body).toContain("<h1");
    expect(head).toContain("Upstream server error");
  });

  test("renders nothing for a failure that resolves by navigating away", () => {
    // 401 sends the user to /logout; rendering the error first would flash it.
    state.page.set({ error: { status: 401, message: "Unauthorized", code: 0 }, url: FAILED_URL });

    const { body } = render(ErrorPage);

    expect(body).not.toContain("Unauthorized");
    expect(body).not.toContain('role="alert"');
  });
});
