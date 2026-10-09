import { page } from "vitest/browser";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { writable } from "svelte/store";
import { m } from "$lib/paraglide/messages";
import type { McpAppBridgeOptions } from "./bridge";
import McpAppFrame from "./McpAppFrame.svelte";
import McpAppFrameHarness from "./McpAppFrameHarness.svelte";

const mocks = vi.hoisted(() => ({
  options: [] as McpAppBridgeOptions[],
  callTool: vi.fn(),
  modes: [] as string[]
}));
vi.mock("../ChatService.svelte", () => ({
  getChatService: () => ({
    partialInputOf: () => undefined,
    getToolCallOutcome: async () => null,
    callToolFromView: mocks.callTool
  })
}));
vi.mock("./McpAppUrlService.svelte", () => ({
  getMcpAppUrlService: () => ({
    get: () => ({ url: "about:blank", html: "<p>Approved app</p>", error: undefined })
  })
}));
vi.mock("$lib/core/theme", () => ({ getThemeStore: () => writable("light") }));
vi.mock("../toolApprovalPreference", () => ({ toolsRunAutomatically: () => true }));
vi.mock("./bridge", () => ({
  McpAppBridge: class {
    constructor(options: McpAppBridgeOptions) {
      mocks.options.push(options);
    }
    setDisplayMode(mode: string) {
      mocks.modes.push(mode);
    }
    update() {}
    contextChanged() {}
    destroy() {}
  }
}));
const call = { tool_call_id: "call-1", tool_name: "table", view: { viewId: "view-1", ui: {} } };

beforeEach(() => {
  mocks.options.length = 0;
  mocks.modes.length = 0;
  mocks.callTool.mockReset().mockResolvedValue({ content: [{ text: "done" }] });
});
describe("McpAppFrame", () => {
  it.each([500, 1000])(
    "retains the iframe, document and bridge at layout width %s",
    async (width) => {
      await page.viewport(1200, 800);
      render(McpAppFrameHarness, { call, width });
      await expect.poll(() => mocks.options.length).toBe(1);
      const frame = document.querySelector("iframe")!;
      const appDocument = frame.contentDocument!;
      appDocument.body.innerHTML = '<input value="retained filter">';
      await page.getByRole("button", { name: "Expand test app" }).click();
      await expect.poll(() => mocks.modes.at(-1)).toBe("fullscreen");
      expect(document.querySelector("iframe")).toBe(frame);
      await expect.poll(() => frame.getBoundingClientRect().height).toBeGreaterThan(300);
      const bounds = frame.getBoundingClientRect();
      expect(document.elementFromPoint(bounds.left + bounds.width / 2, bounds.top + 100)).toBe(
        frame
      );
      frame.focus();
      expect(document.activeElement).toBe(frame);
      expect(frame.contentDocument).toBe(appDocument);
      expect(appDocument.querySelector("input")?.value).toBe("retained filter");
      await page.getByRole("button", { name: "Collapse test app" }).click();
      await expect.poll(() => mocks.modes.at(-1)).toBe("inline");
      expect(document.querySelector("iframe")).toBe(frame);
      expect(mocks.options).toHaveLength(1);
    }
  );

  it("asks for each external call even with automatic model tools enabled", async () => {
    render(McpAppFrameHarness, { call });
    await expect.poll(() => mocks.options.length).toBe(1);
    for (const value of [1, 2]) {
      const result = mocks.options[0].onCallTool!("write", { value });
      await expect.element(page.getByRole("alertdialog")).toBeVisible();
      expect(mocks.callTool).toHaveBeenCalledTimes(value - 1);
      await expect
        .element(page.getByRole("alertdialog").getByText('"value": ' + value, { exact: false }))
        .toBeVisible();
      await page.getByRole("button", { name: m.tool_accept(), exact: true }).click();
      await result;
      expect(mocks.callTool).toHaveBeenCalledTimes(value);
    }
  });

  it("does not reuse a pending approval for a concurrent call", async () => {
    render(McpAppFrameHarness, { call });
    await expect.poll(() => mocks.options.length).toBe(1);
    const first = mocks.options[0].onCallTool!("write", { value: 1 }).catch((error) => error);
    await expect.element(page.getByRole("alertdialog")).toBeVisible();
    await expect(mocks.options[0].onCallTool!("write", { value: 2 })).rejects.toThrow(
      "did not allow"
    );
    await page.getByRole("button", { name: m.tool_deny(), exact: true }).click();
    expect(await first).toBeInstanceOf(Error);
    expect(mocks.callTool).not.toHaveBeenCalled();
  });

  it("keeps the frame's loading attribute when its answer finishes", async () => {
    // Firefox reloads a frame whose `loading` turns lazy, which would be
    // taken for the view navigating away.
    const { rerender } = render(McpAppFrame, { call, live: true });
    await expect.poll(() => mocks.options.length).toBe(1);
    const frame = document.querySelector("iframe")!;
    expect(frame.loading).toBe("eager");
    await rerender({ call, live: false });
    expect(document.querySelector("iframe")).toBe(frame);
    expect(frame.loading).toBe("eager");
  });

  it("lets built-in tools follow the automatic-tool preference", async () => {
    render(McpAppFrameHarness, { call: { ...call, is_bundled: true } });
    await expect.poll(() => mocks.options.length).toBe(1);
    await mocks.options[0].onCallTool!("read", { page: 2 });
    expect(mocks.callTool).toHaveBeenCalledTimes(1);
    expect(page.getByRole("alertdialog").elements()).toHaveLength(0);
  });
});
