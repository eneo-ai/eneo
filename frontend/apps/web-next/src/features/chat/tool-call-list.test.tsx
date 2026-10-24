// @vitest-environment jsdom
import { fireEvent, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import type { ToolCall, ToolPart } from "./activity";
import { ToolCallList } from "./tool-call-list";

const api = vi.hoisted(() => ({ GET: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

afterEach(() => vi.clearAllMocks());

function failedCall(id: string, errorText: string): ToolCall {
  return {
    part: {
      type: "dynamic-tool",
      toolName: "lou_troskelvarden",
      toolCallId: id,
      state: "output-error",
      input: { ar: 2026 },
      errorText,
      providerMetadata: { eneo: { server_name: "lou" } }
    } as ToolPart,
    status: errorText === "failed" ? "error" : "denied",
    approval: null,
    references: []
  };
}

it("shows a failed call's message, and a denial instead of a denied call's stored result", async () => {
  api.GET.mockResolvedValue({
    data: { result: '{"error": "SHORT_HISTORY: too short."}' },
    error: undefined,
    response: new Response("{}", { status: 200 })
  });
  renderInApp(
    <ToolCallList
      calls={[
        failedCall("failed", "failed"),
        failedCall("denied", "denied"),
        failedCall("late", "timeout_denied")
      ]}
      files={[]}
      sessionId="session-1"
      durations={null}
    />
  );
  for (const row of screen.getAllByRole("button", { name: /Lou troskelvarden/ })) {
    fireEvent.click(row);
  }

  expect(await screen.findByText("SHORT_HISTORY: too short.")).toBeTruthy();
  expect(screen.getByText("Nekat")).toBeTruthy();
  expect(screen.getByText("Avvisad, tiden gick ut")).toBeTruthy();
  // A denied call ran nothing: its result is the denial the model read.
  expect(api.GET).toHaveBeenCalledTimes(1);
});
