// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import type { McpAppBridgeOptions } from "./bridge";
import { McpAppFrame } from "./mcp-app-frame";
import { appViewCalls } from "./mcp-apps";
import { messageToolCalls } from "@/features/chat/side-panel/message-tool-calls";

const mocks = vi.hoisted(() => ({
  post: vi.fn(),
  revision: undefined as number | undefined,
  onCallTool: undefined as McpAppBridgeOptions["onCallTool"]
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: { POST: mocks.post } }));
vi.mock("@/features/chat/conversation-settings", () => ({
  useAutomaticToolSettingsRevision: () => mocks.revision
}));
vi.mock("./bridge", () => ({
  McpAppBridge: class {
    constructor(options: McpAppBridgeOptions) {
      mocks.onCallTool = options.onCallTool;
    }
    update = vi.fn();
    destroy = vi.fn();
  }
}));

afterEach(() => {
  cleanup();
  mocks.post.mockReset();
  mocks.revision = undefined;
  mocks.onCallTool = undefined;
});

async function openView(bundled = true) {
  const [call] = appViewCalls(
    messageToolCalls({
      id: "answer",
      role: "assistant",
      parts: [
        {
          type: "dynamic-tool",
          toolName: "query_table",
          toolCallId: "call-1",
          state: "output-available",
          input: {},
          output: {},
          callProviderMetadata: {
            eneo: {
              is_bundled: bundled,
              app_view: { view_id: "view-1", mcp_server_id: "server-1", ui: {} }
            }
          }
        }
      ]
    })
  );
  if (!call) throw new Error("Expected a view");
  const view = renderInApp(
    <McpAppFrame
      call={call}
      live={false}
      startedLive={false}
      sessionId="session-1"
      link={{ url: "about:blank", html: "" }}
      linkError={null}
    />
  );
  const iframe = view.container.querySelector("iframe");
  if (!iframe) throw new Error("Expected a frame");
  await waitFor(() => expect(mocks.onCallTool).toBeTypeOf("function"));
  if (!mocks.onCallTool) throw new Error("Expected a connected view");
  return { ...view, callTool: mocks.onCallTool };
}

const permissionTitle = "Låta vyn köra verktyg?";
const success = () => ({ data: { content: [] }, response: new Response() });
const stale = () => ({
  error: { message: "Settings changed", eneo_error_code: 9065 },
  response: new Response(null, { status: 409 })
});

it("guards an automatic bundled tool call with the resolved settings revision", async () => {
  mocks.revision = 5;
  mocks.post.mockResolvedValueOnce(success());
  const { callTool } = await openView();

  await expect(callTool("query_table", {})).resolves.toEqual({ content: [] });

  expect(mocks.post).toHaveBeenCalledWith(
    "/api/v1/conversations/{session_id}/tool-calls/{tool_call_id}/app-calls/",
    {
      params: { path: { session_id: "session-1", tool_call_id: "call-1" } },
      body: {
        view_id: "view-1",
        name: "query_table",
        arguments: {},
        automatic_settings_revision: 5
      }
    }
  );
  expect(screen.queryByRole("alertdialog", { name: permissionTitle })).toBeNull();
});

it("asks for the same call again after a stale revision and awaits explicit approval", async () => {
  mocks.revision = 5;
  mocks.post.mockResolvedValueOnce(stale()).mockResolvedValueOnce(success());
  const { callTool } = await openView();

  const result = callTool("query_table", { table: "orders" }).then(
    (value) => ({ value }),
    (error: unknown) => ({ error })
  );
  const dialog = await screen.findByRole("alertdialog", { name: permissionTitle });
  expect(mocks.post).toHaveBeenCalledTimes(1);
  expect(dialog.textContent).toContain("orders");
  fireEvent.click(within(dialog).getByRole("button", { name: "Godkänn" }));

  await expect(result).resolves.toEqual({ value: { content: [] } });
  expect(mocks.post).toHaveBeenLastCalledWith(
    "/api/v1/conversations/{session_id}/tool-calls/{tool_call_id}/app-calls/",
    {
      params: { path: { session_id: "session-1", tool_call_id: "call-1" } },
      body: { view_id: "view-1", name: "query_table", arguments: { table: "orders" } }
    }
  );
});

it.each([
  ["an external view", false, 5],
  ["a bundled view without a revision", true, undefined]
] as const)("asks before calling from %s", async (_label, bundled, revision) => {
  mocks.revision = revision;
  const { callTool, unmount } = await openView(bundled);
  let result!: Promise<unknown>;
  act(() => {
    result = callTool("query_table", {});
  });
  const rejected = expect(result).rejects.toThrow("The user did not allow the tool call");
  await screen.findByRole("alertdialog", { name: permissionTitle });
  unmount();
  await rejected;
  expect(mocks.post).not.toHaveBeenCalled();
});
