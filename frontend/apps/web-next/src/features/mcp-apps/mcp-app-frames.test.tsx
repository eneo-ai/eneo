// @vitest-environment jsdom
import { act, cleanup, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { EneoUIMessage } from "@/lib/chat/types";
import { renderInApp } from "@/test/render";

// The frame's code (the MCP app bridge) arrives on demand. Each test starts from
// fresh modules and a fresh mock, decides when the code arrives and whether it
// can be fetched (its chunk is gone after a deploy).
const state = { loads: 0, fail: false, linksAsked: [] as string[] };
let arrive = () => {};
beforeEach(() => {
  vi.resetModules();
  state.loads = 0;
  state.fail = false;
  state.linksAsked = [];
  const arrived = new Promise<void>((resolve) => (arrive = resolve));
  vi.doMock("./use-view-link", () => ({
    useViewLink: (viewId: string) => {
      state.linksAsked.push(viewId);
      return { link: null, error: null };
    }
  }));
  vi.doMock("./mcp-app-frame", async () => {
    state.loads += 1;
    await arrived;
    if (state.fail) throw new Error("Failed to fetch dynamically imported module");
    return {
      McpAppFrame: ({
        call,
        startedLive
      }: {
        call: { toolCallId: string };
        startedLive: boolean;
      }) => <p>{`Frame for ${call.toolCallId}${startedLive ? ", started live" : ""}`}</p>
    };
  });
});
afterEach(cleanup);

type Part = EneoUIMessage["parts"][number];

function answer(appView: Record<string, unknown> | null, toolCallId = "call-1"): EneoUIMessage {
  return {
    id: `answer-${toolCallId}`,
    role: "assistant",
    parts: [
      {
        type: "dynamic-tool",
        toolName: "query_table",
        toolCallId,
        state: "output-available",
        input: {},
        output: { status: "succeeded" },
        callProviderMetadata: {
          eneo: { server_name: "runtime", is_bundled: true, app_view: appView, approved: null }
        }
      } as unknown as Part
    ]
  };
}

const view = { view_id: "view-1", mcp_server_id: "server-1", ui: {} };

async function renderFrames(message: EneoUIMessage, live = false) {
  const { McpAppFrames } = await import("./mcp-app-frames");
  return renderInApp(<McpAppFrames message={message} live={live} sessionId="session-1" />);
}

it("loads no frame code for an answer without app views", async () => {
  const { container } = await renderFrames(answer(null));
  await act(async () => arrive());
  expect(container.textContent).toBe("");
  expect(state.loads).toBe(0);
});

it("holds an earlier answer's place while the frame code arrives, then shows the frame", async () => {
  const { container } = await renderFrames(answer(view));
  const placeholder = container.querySelector<HTMLElement>("[aria-hidden='true']");
  expect(placeholder?.style.height).toBe("320px");

  await act(async () => arrive());
  expect(await screen.findByText("Frame for call-1")).toBeTruthy();
});

it("asks for the view's link while the frame code arrives", async () => {
  await renderFrames(answer(view));
  expect(state.linksAsked).toContain("view-1");
});

it("takes no room for the live answer's view while its code arrives", async () => {
  const { container } = await renderFrames(answer(view), true);
  expect(container.querySelector<HTMLElement>("[aria-hidden='true']")?.className).toContain(
    "hidden"
  );
});

it("keeps how a live answer's view started when the answer finishes before the code arrives", async () => {
  const { container, rerender } = await renderFrames(answer(view), true);
  const { McpAppFrames } = await import("./mcp-app-frames");
  rerender(<McpAppFrames message={answer(view)} live={false} sessionId="session-1" />);
  expect(container.querySelector<HTMLElement>("[aria-hidden='true']")?.className).toContain(
    "hidden"
  );

  await act(async () => arrive());
  expect(await screen.findByText("Frame for call-1, started live")).toBeTruthy();
});

it("says the view is unavailable when its code cannot be fetched, and the next view tries again", async () => {
  state.fail = true;
  const { McpAppFrames } = await import("./mcp-app-frames");
  const { rerender } = await renderFrames(answer(view));
  await act(async () => arrive());
  expect(await screen.findByRole("note")).toBeTruthy();
  const attempts = state.loads;

  // The same view, re-rendered as its answer changes, keeps its note.
  rerender(<McpAppFrames message={answer(view)} live sessionId="session-1" />);
  await act(async () => {});
  expect(screen.getByRole("note")).toBeTruthy();
  expect(state.loads).toBe(attempts);

  // The next view to appear loads the code anew.
  state.fail = false;
  rerender(
    <>
      <McpAppFrames message={answer(view)} live={false} sessionId="session-1" />
      <McpAppFrames message={answer(view, "call-2")} live={false} sessionId="session-1" />
    </>
  );
  expect(await screen.findByText("Frame for call-2")).toBeTruthy();
  expect(state.loads).toBeGreaterThan(attempts);
});
