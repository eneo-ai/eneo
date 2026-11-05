import { describe, expect, it } from "vitest";
import type { components } from "@eneo/eneo-js";
import { referenceAuditRows } from "@eneo/skill-instructions/audit";

type Schema = components["schemas"];
const reference = {
  activation_key: "guide",
  skill_id: "guide",
  skill_revision_id: "revision-1",
  revision_number: 2,
  content_digest: "a".repeat(64),
  position: 0,
  source: "space",
  display_name: "Guide"
} satisfies Schema["SkillActivationReference"];
const evidence = {
  version: 3,
  available: [reference],
  blocked: [],
  initially_active: ["guide"],
  selected_model_id: "model",
  selected_model_route: "test/model",
  skill_context_tokens: 10,
  skill_context_token_limit: 100,
  token_count_source: "litellm",
  effective_mode: "selective",
  references_prepared: true
} satisfies Schema["SkillActivationEvidenceV3"];
const time = {
  model_name: "time_now",
  server_id: "time-server",
  tool_name: "now",
  purpose: "general"
} satisfies Schema["ModelToolIdentity"];

describe("observed instruction reference evidence", () => {
  it("distinguishes offered tools, observed calls and unprepared turns", () => {
    const snapshot: Schema["SkillActivationEvidenceV3"] = {
      ...evidence,
      instruction_references: [
        {
          source_revision_id: "revision-1",
          label: "Time",
          target: { kind: "mcp_server", server_id: "time-server" }
        }
      ],
      reference_tools: [time]
    };
    expect(referenceAuditRows(snapshot, [])[0]?.state).toBe("available");
    expect(referenceAuditRows({ ...snapshot, reference_tools: [] }, [])[0]?.state).toBe(
      "unavailable"
    );
    expect(
      referenceAuditRows({ ...snapshot, reference_tools: [], references_prepared: false }, [])[0]
        ?.state
    ).toBe("not_checked");
    const calls: Schema["ToolCallInfo"][] = [
      { server_name: "other", tool_name: "now", mcp_tool_name: "other_now" },
      { server_name: "Time", tool_name: "now", mcp_tool_name: "time_now", result_status: "failed" }
    ];
    expect(
      referenceAuditRows(snapshot, [{ server_name: "Time", tool_name: "now" }])[0]?.state
    ).toBe("available");
    expect(referenceAuditRows(snapshot, calls)[0]).toMatchObject({
      state: "called",
      callOrders: [2],
      source: "Guide",
      sourceRevision: 2
    });
  });
  it("matches functions by purpose and specific MCP tools by exact server and protocol name", () => {
    const snapshot: Schema["SkillActivationEvidenceV3"] = {
      ...evidence,
      instruction_references: [
        {
          source_revision_id: "revision-1",
          label: "Search",
          target: { kind: "function", purpose: "web_search" }
        },
        {
          source_revision_id: "revision-1",
          label: "Time",
          target: { kind: "mcp_tool", server_id: "time-server", tool_name: "today" }
        },
        {
          source_revision_id: "revision-1",
          label: "Other",
          target: { kind: "mcp_server", server_id: "other-server" }
        }
      ],
      reference_tools: [
        time,
        {
          model_name: "search_web",
          server_id: "search-server",
          tool_name: "search",
          purpose: "web_search"
        }
      ]
    };
    const calls = [{ server_name: "Search", tool_name: "search", mcp_tool_name: "search_web" }];
    expect(referenceAuditRows(snapshot, calls).map((row) => row.state)).toEqual([
      "called",
      "unavailable",
      "unavailable"
    ]);
    expect(
      referenceAuditRows(snapshot, [{ ...calls[0]!, mcp_tool_name: "different" }])[0]?.state
    ).toBe("available");
  });
  it("identifies helper sources and deduplicates repeated mentions without inventing call causality", () => {
    const snapshot: Schema["SkillActivationEvidenceV3"] = {
      ...evidence,
      helpers: [
        {
          ...reference,
          activation_key: null,
          skill_id: "helper",
          skill_revision_id: "helper-1",
          display_name: "Klartext"
        }
      ],
      instruction_references: [
        {
          source_revision_id: "revision-1",
          label: "Klartext",
          target: { kind: "skill", skill_id: "helper", revision_id: "helper-1" }
        },
        {
          source_revision_id: "helper-1",
          label: "Time",
          target: { kind: "mcp_server", server_id: "time-server" }
        },
        {
          source_revision_id: "helper-1",
          label: "Time again",
          target: { kind: "mcp_server", server_id: "time-server" }
        }
      ],
      reference_tools: [time]
    };
    const rows = referenceAuditRows(snapshot, []);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({ source: "Guide", state: "loaded", callOrders: [] });
    expect(rows[1]).toMatchObject({ source: "Klartext", state: "available", callOrders: [] });
  });
});
