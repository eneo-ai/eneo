import { describe, expect, it } from "vitest";
import type { EneoUIMessage } from "@/lib/chat/types";
import { finishedToolCallIds, newlyFinishedToolCalls } from "./finished-tool-calls";

function answer(calls: { id: string; state: string }[]): EneoUIMessage {
  return {
    id: `answer-${calls.map((call) => call.id).join("-")}`,
    role: "assistant",
    parts: calls.map((call) => ({
      type: "dynamic-tool",
      toolCallId: call.id,
      toolName: "update_step",
      state: call.state,
      input: {},
      ...(call.state === "output-available" ? { output: {} } : {}),
      ...(call.state === "output-error" ? { errorText: "refused" } : {})
    }))
  } as EneoUIMessage;
}

describe("finished tool calls", () => {
  it("takes the calls that have a result or failed", () => {
    const messages = [
      answer([
        { id: "done", state: "output-available" },
        { id: "failed", state: "output-error" },
        { id: "running", state: "input-available" }
      ])
    ];
    expect(finishedToolCallIds(messages)).toEqual(["done", "failed"]);
  });

  it("reports each call once, as it finishes", () => {
    const seen = new Set(["earlier"]);
    const streaming = [
      answer([{ id: "earlier", state: "output-available" }]),
      answer([{ id: "new", state: "input-available" }])
    ];
    expect(newlyFinishedToolCalls(streaming, seen)).toEqual([]);

    const finished = [streaming[0]!, answer([{ id: "new", state: "output-available" }])];
    expect(newlyFinishedToolCalls(finished, seen).map((call) => call.toolCallId)).toEqual(["new"]);
    expect(newlyFinishedToolCalls(finished, seen)).toEqual([]);
  });
});
