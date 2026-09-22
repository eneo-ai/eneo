import { describe, expect, it, vi } from "vitest";
import type { ConversationMessage } from "@eneo/eneo-js";
import { stepServers, widgetToolSteps } from "./widgetToolSteps";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, (params?: Record<string, unknown>) => string>>(
    {},
    {
      get: (_target, key) => (params?: Record<string, unknown>) =>
        `${String(key)}${params ? " " + JSON.stringify(params) : ""}`
    }
  )
}));

function message(calls: Record<string, unknown>[], runtime = false): ConversationMessage {
  return {
    id: "m",
    question: "q",
    answer: "",
    references: [],
    ...(runtime ? { mcp_tool_calls: calls } : { tool_calls: calls })
  } as unknown as ConversationMessage;
}

const search = (extra: Record<string, unknown> = {}) => ({
  server_name: "Safe Search",
  tool_name: "search",
  purpose: "web_search",
  arguments: { query: "bygglov" },
  tool_call_id: "c1",
  ...extra
});

describe("widgetToolSteps", () => {
  it("labels capability calls by purpose and keeps the provider as detail", () => {
    const [step] = widgetToolSteps(message([search({ result_status: "completed" })]), {
      streaming: false,
      working: false
    });
    expect(step.toolName).toContain("tool_web_search_query");
    expect(step.doneLabel).toContain("tool_web_search_query_done");
    expect(step.detail).toBe("Safe Search");
    expect(step.status).toBe("complete");
  });

  it("prefers the streaming runtime list over the persisted one", () => {
    const steps = widgetToolSteps(message([search(), search({ tool_call_id: "c2" })], true), {
      streaming: true,
      working: true
    });
    expect(steps.map((step) => step.toolCallId)).toEqual(["c1", "c2"]);
    expect(steps[1].status).toBe("running");
  });

  it("shows a pending call as failed once the stream has ended", () => {
    const [live] = widgetToolSteps(message([search({ result_status: "pending" })]), {
      streaming: true,
      working: false
    });
    const [dead] = widgetToolSteps(message([search({ result_status: "pending" })]), {
      streaming: false,
      working: false
    });
    expect(live.status).toBe("preparing");
    expect(dead.status).toBe("failed");
  });

  it("marks denied and failed calls", () => {
    const steps = widgetToolSteps(
      message([
        search({ approved: false }),
        search({ tool_call_id: "c2", result_status: "failed" })
      ]),
      { streaming: false, working: false }
    );
    expect(steps.map((step) => step.status)).toEqual(["denied", "failed"]);
  });

  it("lists distinct servers in first-seen order", () => {
    const steps = widgetToolSteps(
      message([
        search({ result_status: "completed" }),
        {
          server_name: "Tid",
          tool_name: "get_current_time",
          tool_call_id: "c2",
          result_status: "completed"
        },
        search({ tool_call_id: "c3", result_status: "completed" })
      ]),
      { streaming: false, working: false }
    );
    // The capability call is labelled by purpose, not by its provider.
    expect(steps[0].serverName).not.toBe("Safe Search");
    expect(stepServers(steps)).toEqual([steps[0].serverName, "Tid"]);
  });
});
