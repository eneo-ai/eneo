import { describe, expect, it, vi } from "vitest";
import type { ConversationMessage } from "@eneo/eneo-js";
import {
  argumentDetail,
  groupToolSteps,
  creditedServers,
  humanizeToolName,
  widgetToolSteps
} from "./widgetToolSteps";

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

const time = (id: string, timezone: string, extra: Record<string, unknown> = {}) => ({
  server_name: "TimeMCP",
  tool_name: "get_current_time",
  arguments: { timezone },
  tool_call_id: id,
  result_status: "completed",
  ...extra
});

const search = (extra: Record<string, unknown> = {}) => ({
  server_name: "Safe Search",
  tool_name: "search",
  purpose: "web_search",
  arguments: { query: "bygglov" },
  tool_call_id: "s1",
  result_status: "completed",
  ...extra
});

describe("humanizeToolName", () => {
  it("prefers the catalog title and otherwise spells the tool name out", () => {
    expect(humanizeToolName("get_current_time", "Aktuell tid")).toBe("Aktuell tid");
    expect(humanizeToolName("get_current_time")).toBe("Get current time");
    expect(humanizeToolName("convertTime")).toBe("Convert time");
  });
});

describe("argumentDetail", () => {
  it("picks the telling argument and shortens long ones", () => {
    expect(argumentDetail({ format: "24h", timezone: "Asia/Tokyo" })).toBe("Asia/Tokyo");
    expect(argumentDetail({ limit: 5 })).toBeNull();
    expect(argumentDetail({ query: "x".repeat(80) })?.length).toBe(48);
    expect(argumentDetail(null)).toBeNull();
  });
});

describe("widgetToolSteps", () => {
  it("labels external tools by name with one argument as detail", () => {
    const [step] = widgetToolSteps(message([time("c1", "Asia/Tokyo")]), {
      streaming: false,
      working: false
    });
    expect(step).toMatchObject({
      label: "Get current time",
      summary: "Get current time",
      detail: "Asia/Tokyo",
      serverName: "TimeMCP",
      via: "TimeMCP",
      status: "complete"
    });
  });

  it("credits no server for Eneo's own knowledge search and sums it up without the query", () => {
    const [step] = widgetToolSteps(
      message([
        {
          server_name: "knowledge",
          tool_name: "search_knowledge",
          arguments: { query: "kaffe rekommendationer tips" },
          tool_call_id: "k1",
          result_status: "completed"
        }
      ]),
      { streaming: false, working: false }
    );
    expect(step).toMatchObject({
      label: 'tool_search_knowledge_query_done {"query":"kaffe rekommendationer tips"}',
      summary: "tool_search_knowledge_done",
      detail: null,
      via: null
    });
  });

  it("labels capability calls by purpose, query included, without a detail chip", () => {
    const [step] = widgetToolSteps(message([search()]), { streaming: false, working: false });
    expect(step.label).toContain("tool_web_search_query_done");
    expect(step.summary).toBe("tool_web_search_done");
    expect(step.detail).toBeNull();
    expect(step.serverName).not.toBe("Safe Search");
    expect(step.via).toBeNull();
  });

  it("prefers the streaming runtime list and marks the last call as running", () => {
    const steps = widgetToolSteps(message([time("c1", "UTC"), time("c2", "Europe/Oslo")], true), {
      streaming: true,
      working: true
    });
    expect(steps.map((step) => step.toolCallId)).toEqual(["c1", "c2"]);
    expect(steps[1].status).toBe("running");
  });

  it("shows a pending call as failed once the stream has ended", () => {
    const pending = time("c1", "UTC", { result_status: "pending" });
    expect(widgetToolSteps(message([pending]), { streaming: true, working: false })[0].status).toBe(
      "preparing"
    );
    expect(
      widgetToolSteps(message([pending]), { streaming: false, working: false })[0].status
    ).toBe("failed");
  });

  it("marks denied and failed calls", () => {
    const steps = widgetToolSteps(
      message([
        time("c1", "UTC", { approved: false }),
        time("c2", "UTC", { result_status: "failed" })
      ]),
      { streaming: false, working: false }
    );
    expect(steps.map((step) => step.status)).toEqual(["denied", "failed"]);
  });
});

describe("groupToolSteps", () => {
  it("folds consecutive calls of the same tool and keeps the order of servers", () => {
    const steps = widgetToolSteps(
      message([time("c1", "UTC"), time("c2", "Asia/Tokyo"), search(), time("c3", "Europe/London")]),
      { streaming: false, working: false }
    );
    const groups = groupToolSteps(steps);
    expect(groups.map((group) => group.steps.length)).toEqual([2, 1, 1]);
    expect(groups[0].steps.map((step) => step.detail)).toEqual(["UTC", "Asia/Tokyo"]);
    // The web search label already says where it looked.
    expect(creditedServers(steps)).toEqual(["TimeMCP"]);
  });
});
