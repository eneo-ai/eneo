// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";

// The SDK stands in for the view: it reports the view as started and keeps
// the results it is handed.
const sdk = vi.hoisted(() => ({
  listeners: new Map<string, () => void>(),
  results: [] as unknown[]
}));
vi.mock("@modelcontextprotocol/ext-apps/app-bridge", () => ({
  PostMessageTransport: class {},
  AppBridge: class {
    addEventListener(type: string, listener: () => void) {
      sdk.listeners.set(type, listener);
    }
    getAppCapabilities() {
      return {};
    }
    async connect() {}
    async sendToolInput() {}
    async sendToolResult(result: unknown) {
      sdk.results.push(result);
    }
    async teardownResource() {}
    close() {}
  }
}));

import { EneoApiError } from "@/lib/api/errors";
import { McpAppBridge, type ToolCallOutcome } from "./bridge";

const notStored = () => new EneoApiError("Not found", { status: 404 });

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  sdk.listeners.clear();
  sdk.results.length = 0;
  document.body.replaceChildren();
});

/** A started view whose call has finished, so it asks for the result. */
function finishedView(getToolResult: () => Promise<ToolCallOutcome | null>) {
  const iframe = document.createElement("iframe");
  document.body.append(iframe);
  const bridge = new McpAppBridge({ iframe, html: "", displayMode: "inline", getToolResult });
  sdk.listeners.get("initialized")!();
  bridge.update({ input: {}, resultReady: true });
  return bridge;
}

// A stopped answer is stored once its stream has ended: for a moment its
// result is not there yet (404).
it("asks again for a result that is not stored yet", async () => {
  const getToolResult = vi
    .fn()
    .mockRejectedValueOnce(notStored())
    .mockRejectedValueOnce(notStored())
    .mockResolvedValue({ result: "rows" });
  finishedView(getToolResult);

  await vi.advanceTimersByTimeAsync(1500);
  expect(getToolResult).toHaveBeenCalledTimes(3);
  expect(sdk.results).toEqual([{ content: [{ type: "text", text: "rows" }] }]);
});

it("stops asking after the last try, or once the view is gone", async () => {
  const missing = vi.fn().mockRejectedValue(notStored());
  finishedView(missing);
  await vi.advanceTimersByTimeAsync(60_000);
  expect(missing).toHaveBeenCalledTimes(5);

  const gone = vi.fn().mockRejectedValue(notStored());
  finishedView(gone).destroy();
  await vi.advanceTimersByTimeAsync(60_000);
  expect(gone).toHaveBeenCalledTimes(1);
  expect(sdk.results).toEqual([]);
});

it("does not ask again when the result is refused or the request fails otherwise", async () => {
  const refused = vi.fn().mockRejectedValue(new EneoApiError("Forbidden", { status: 403 }));
  finishedView(refused);
  await vi.advanceTimersByTimeAsync(60_000);
  expect(refused).toHaveBeenCalledTimes(1);
  expect(sdk.results).toEqual([]);
});
