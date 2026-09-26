import { describe, expect, it } from "vitest";
import type { EneoUIMessage } from "@/lib/chat/types";
import { currentStep, deriveActivity } from "./activity";
import { ActivityTimings } from "./activity-timings";

type Part = EneoUIMessage["parts"][number];

const knowledge = [
  { id: "group-1", name: "Upphandlingspolicy", kind: "collection" as const },
  { id: "site-1", name: "LOU-vägledning", kind: "website" as const }
];

const doc = (sourceId: string, title: string, origin: { group_id?: string; website_id?: string }) =>
  ({
    type: "source-document",
    sourceId,
    mediaType: "text/plain",
    title,
    providerMetadata: { eneo: { id: sourceId, metadata: { title }, ...origin } }
  }) as Part;

const tool = (id: string, state: string, extra: Record<string, unknown> = {}) =>
  ({
    type: "dynamic-tool",
    toolName: "lou_troskelvarden",
    toolCallId: id,
    state,
    input: { ar: 2026 },
    providerMetadata: { eneo: { server_name: "lou", title: null, purpose: null } },
    ...extra
  }) as Part;

function assistant(parts: Part[], metadata: EneoUIMessage["metadata"] = {}): EneoUIMessage {
  return { id: "a-1", role: "assistant", parts, metadata };
}

describe("deriveActivity", () => {
  it("orders retrieval, reasoning, tools and the answer as steps with named origins", () => {
    const activity = deriveActivity(
      assistant(
        [
          doc("d1", "Policy.pdf", { group_id: "group-1" }),
          doc("d2", "LOU 19 kap.", { website_id: "site-1" }),
          doc("d3", "Bilaga.pdf", { group_id: "group-1" }),
          { type: "reasoning", text: "Jämför tre kommuner.", state: "done" },
          tool("call-1", "output-available", { output: { status: "succeeded" } }),
          { type: "text", text: "Svaret.", state: "done" }
        ],
        {
          completionModel: { id: "m", name: "claude-haiku-4-5", nickname: "Claude Haiku 4.5" },
          tokens: { completion: 1842 }
        }
      ),
      { knowledge }
    );

    expect(activity.steps.map((step) => step.kind)).toEqual([
      "knowledge",
      "reasoning",
      "tool",
      "answer"
    ]);
    const retrieval = activity.steps[0]!;
    expect(retrieval).toMatchObject({ kind: "knowledge", hits: 3 });
    if (retrieval.kind === "knowledge") {
      expect(retrieval.origins.map((origin) => origin.name)).toEqual([
        "Upphandlingspolicy",
        "LOU-vägledning"
      ]);
    }
    expect(activity.steps.at(-1)).toMatchObject({
      kind: "answer",
      status: "done",
      model: "Claude Haiku 4.5",
      tokens: 1842
    });
    expect(activity.sources.map((source) => [source.title, source.origin])).toEqual([
      ["Policy.pdf", "Upphandlingspolicy"],
      ["LOU 19 kap.", "LOU-vägledning"],
      ["Bilaga.pdf", "Upphandlingspolicy"]
    ]);
    expect(activity.hasActivity).toBe(true);
    expect(activity.errorCount).toBe(0);
  });

  it("has nothing to show for a plain answer", () => {
    const activity = deriveActivity(assistant([{ type: "text", text: "Hej!", state: "done" }]));
    expect(activity.hasActivity).toBe(false);
    expect(activity.sources).toEqual([]);
  });

  it("records approvals from persisted calls and the stream's approval parts", () => {
    const activity = deriveActivity(
      assistant([
        tool("call-1", "output-available", {
          providerMetadata: { eneo: { server_name: "jira", approved: true } }
        }),
        tool("call-2", "output-error", { errorText: "timeout_denied" }),
        {
          type: "data-tool-approval",
          id: "appr-1",
          data: {
            approval_id: "appr-1",
            status: "timeout_denied",
            tools: [{ server_name: "slack", tool_name: "post", tool_call_id: "call-2" }]
          }
        }
      ])
    );
    const [approved, denied] = activity.steps;
    expect(approved).toMatchObject({ kind: "tool", status: "done", approval: "approved" });
    expect(denied).toMatchObject({ kind: "tool", status: "denied", approval: "denied" });
  });

  it("names the running step while streaming and stops unfinished steps afterwards", () => {
    const parts: Part[] = [
      { type: "reasoning", text: "Tänker…", state: "done" },
      tool("call-1", "input-available")
    ];
    const live = deriveActivity(assistant(parts), { streaming: true });
    expect(live.running).toBe(true);
    expect(currentStep(live)).toMatchObject({ kind: "tool", status: "running" });

    const stopped = deriveActivity(assistant(parts));
    expect(stopped.steps.at(-1)).toMatchObject({ kind: "tool", status: "stopped" });
    expect(currentStep(stopped)).toBeNull();
  });

  it("counts failed tool calls as errors", () => {
    const activity = deriveActivity(
      assistant([tool("call-1", "output-error", { errorText: "TimeoutError" })])
    );
    expect(activity.errorCount).toBe(1);
  });

  it("lists MCP resources under the tool call that read them", () => {
    const reference = {
      id: "ref-1",
      uri: "eneo://docs/policy",
      content: "…",
      tool_call_id: "call-1",
      meta: { title: "Policy", pageRange: "4, 9" }
    };
    const activity = deriveActivity(
      assistant([
        tool("call-1", "output-available"),
        { type: "data-mcp-tool-references", data: { mcp_tool_references: [reference] } }
      ])
    );
    const step = activity.steps[0]!;
    expect(step.kind === "tool" && step.references.map((ref) => ref.id)).toEqual(["ref-1"]);
    expect(activity.sources[0]).toMatchObject({ title: "Policy", pageRange: "4, 9" });
  });

  it("never labels a section as a page range", () => {
    const reference = {
      id: "ref-2",
      uri: "eneo://docs/policy",
      content: "…",
      tool_call_id: "call-1",
      meta: { title: "Policy", section: "Avsnitt 4" }
    };
    const activity = deriveActivity(
      assistant([
        tool("call-1", "output-available"),
        { type: "data-mcp-tool-references", data: { mcp_tool_references: [reference] } }
      ])
    );
    expect(activity.sources[0]).toMatchObject({ pageRange: null });
    expect(activity.sources[0]?.title).toContain("Avsnitt 4");
  });
});

describe("ActivityTimings", () => {
  it("measures a streamed turn and its steps, and nothing for history", () => {
    const timings = new ActivityTimings();
    const user: EneoUIMessage = { id: "u-1", role: "user", parts: [] };
    let listened = 0;
    timings.subscribe(() => listened++);

    timings.markSent(1_000);
    const thinking = assistant([{ type: "reasoning", text: "…", state: "streaming" }]);
    timings.observe([user, thinking], true, 1_500);
    const thought = assistant([
      { type: "reasoning", text: "…", state: "done" },
      { type: "text", text: "Svar", state: "streaming" }
    ]);
    timings.observe([user, thought], true, 2_700);
    timings.markTokens(120);
    timings.observe([user, thought], false, 4_000);

    expect(timings.durations("a-1")).toEqual({
      totalMs: 3_000,
      stepMs: { "reasoning-0": 1_200, answer: 1_300 },
      tokens: 120,
      finishedAt: new Date(4_000).toISOString()
    });
    expect(timings.durations("history-1")).toBeNull();
    expect(listened).toBeGreaterThan(0);
  });
});
