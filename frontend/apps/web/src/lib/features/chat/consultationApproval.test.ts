import { describe, expect, it } from "vitest";
import { awaitingToolCalls, isAwaitingApproval } from "./consultationApproval";

const step = (
  tool_call_id: string,
  overrides: Partial<
    NonNullable<Parameters<typeof awaitingToolCalls>[0]["tool_calls"]>[number]
  > = {}
) => ({
  server_name: "inventory",
  tool_name: "lookup",
  tool_call_id,
  result_status: "pending",
  ...overrides
});

describe("awaitingToolCalls", () => {
  it("lists only the calls the backend says the approval decides", () => {
    const consultation = {
      status: "awaiting_approval",
      approval_id: "approval-1",
      awaiting_tool_call_ids: ["external"],
      tool_calls: [
        step("internal", { server_name: "knowledge", tool_name: "search", is_internal: true }),
        step("earlier", { result_status: "failed" }),
        step("external", { result_status: "awaiting_approval", arguments: { q: "x" } })
      ]
    };
    expect(awaitingToolCalls(consultation)).toEqual([
      {
        server_name: "inventory",
        tool_name: "lookup",
        arguments: { q: "x" },
        tool_call_id: "external"
      }
    ]);
    expect(isAwaitingApproval(consultation, { tool_call_id: "external" })).toBe(true);
    expect(isAwaitingApproval(consultation, { tool_call_id: "internal" })).toBe(false);
  });

  it("falls back to external pending steps for history without the list", () => {
    const consultation = {
      status: "awaiting_approval",
      approval_id: "approval-1",
      tool_calls: [
        step("internal", { is_internal: true }),
        step("done", { result_status: "succeeded" }),
        step("failed", { result_status: "failed" }),
        step("external")
      ]
    };
    expect(awaitingToolCalls(consultation).map((call) => call.tool_call_id)).toEqual(["external"]);
  });

  it("is empty unless the consultation is waiting with an approval id", () => {
    expect(
      awaitingToolCalls({
        status: "running",
        approval_id: null,
        awaiting_tool_call_ids: ["external"],
        tool_calls: [step("external")]
      })
    ).toEqual([]);
    expect(
      awaitingToolCalls({
        status: "awaiting_approval",
        approval_id: undefined,
        tool_calls: [step("external")]
      })
    ).toEqual([]);
  });
});
