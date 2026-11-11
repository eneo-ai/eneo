// @vitest-environment jsdom
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EneoUIMessage } from "@/lib/chat/types";
import { renderInApp, testQueryClient } from "@/test/render";
import type { ToolCall } from "./activity";
import { ToolCallList } from "./tool-call-list";

const api = vi.hoisted(() => ({ GET: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

type Part = EneoUIMessage["parts"][number];

const call: ToolCall = {
  part: {
    type: "dynamic-tool",
    toolName: "read_flow",
    toolCallId: "call-1",
    state: "output-available",
    input: { section: "overview" },
    output: { status: "succeeded" },
    providerMetadata: { eneo: { server_name: "flows", approved: true } }
  } as Part as ToolCall["part"],
  status: "done",
  approval: null,
  references: []
};

const second: ToolCall = {
  ...call,
  part: { ...call.part, toolName: "list_steps", toolCallId: "call-2" } as ToolCall["part"]
};

const failed: ToolCall = {
  part: {
    type: "dynamic-tool",
    toolName: "read_flow",
    toolCallId: "call-3",
    state: "output-error",
    input: { section: "overview" },
    errorText: "Flödet finns inte.",
    providerMetadata: { eneo: { server_name: "flows", approved: true } }
  } as Part as ToolCall["part"],
  status: "error",
  approval: null,
  references: []
};

const found = () => ({
  data: { tool_call_id: "call-1", result: "Flödet har 1 steg." },
  response: new Response(null, { status: 200 })
});
const notYet = () => ({
  data: undefined,
  error: { detail: "Tool call not found in this session" },
  response: new Response(null, { status: 404 })
});

const list = (stored: boolean, calls: ToolCall[] = [call]) => (
  <ToolCallList calls={calls} files={[]} sessionId="session-1" durations={null} stored={stored} />
);

/** Lets every request already due go out and settle. */
const settle = () => new Promise((resolve) => setTimeout(resolve, 50));

beforeEach(() => api.GET.mockReset());
afterEach(cleanup);

describe("ToolCallList", () => {
  it("asks for a finished call's result only once its row is opened", async () => {
    api.GET.mockImplementation(async () => found());
    renderInApp(list(true, [call, second]));
    expect(api.GET).not.toHaveBeenCalled();
    fireEvent.click(screen.getAllByRole("button", { expanded: false })[0]!);
    expect(await screen.findByText("Flödet har 1 steg.")).toBeTruthy();
    await settle();
    expect(api.GET).toHaveBeenCalledTimes(1);
    expect(api.GET.mock.calls[0]![1].params.path.tool_call_id).toBe("call-1");
  });

  it("while the answer is written, says the result comes with it, and asks once the answer is stored", async () => {
    api.GET.mockImplementation(async () => found());
    const { rerender } = renderInApp(list(false));
    fireEvent.click(screen.getByRole("button", { expanded: false }));
    expect(screen.getByText("Resultatet visas när svaret är klart.")).toBeTruthy();
    expect(screen.queryByText("Kunde inte hämta verktygssvaret")).toBeNull();
    expect(api.GET).not.toHaveBeenCalled();
    rerender(list(true));
    expect(await screen.findByText("Flödet har 1 steg.")).toBeTruthy();
  });

  it("asks again when the answer's save has not reached the server yet", async () => {
    api.GET.mockImplementationOnce(async () => notYet()).mockImplementation(async () => found());
    renderInApp(list(true));
    fireEvent.click(screen.getByRole("button", { expanded: false }));
    expect(
      await screen.findByText("Flödet har 1 steg.", undefined, { timeout: 3_000 })
    ).toBeTruthy();
    expect(screen.queryByText("Kunde inte hämta verktygssvaret")).toBeNull();
  });

  it("gives up after three more tries when the result is never found", async () => {
    api.GET.mockImplementation(async () => notYet());
    const queryClient = testQueryClient();
    queryClient.setDefaultOptions({
      ...queryClient.getDefaultOptions(),
      queries: { ...queryClient.getDefaultOptions().queries, retryDelay: 0 }
    });
    renderInApp(list(true), { queryClient });
    fireEvent.click(screen.getByRole("button", { expanded: false }));
    expect(await screen.findByText("Kunde inte hämta verktygssvaret")).toBeTruthy();
    await settle();
    expect(api.GET).toHaveBeenCalledTimes(4);
  });

  it("shows a failed call's error while the answer is written, without asking", async () => {
    renderInApp(list(false, [failed]));
    fireEvent.click(screen.getByRole("button", { expanded: false }));
    expect(screen.getAllByText("Flödet finns inte.")).toHaveLength(2);
    expect(screen.queryByText("Resultatet visas när svaret är klart.")).toBeNull();
    await settle();
    expect(api.GET).not.toHaveBeenCalled();
  });
});
