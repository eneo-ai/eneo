import { describe, expect, it } from "vitest";
import {
  buildSkillActivationRows,
  listDebugTurns,
  projectTurnDebugDetails,
  readToolUsage,
  summarizeSkillActivation,
  unmatchedActivationRejections,
  type PersistedMessage,
  type SkillActivationEvidence
} from "./turn-debug";

const file = (id: string, name: string) => ({
  id,
  name,
  mimetype: "application/pdf",
  size: 1024,
  created_at: null,
  updated_at: null,
  checksum: "x",
  transcription: null
});

const message = {
  id: "m-1",
  created_at: "2026-10-01T08:30:00Z",
  question: "Vad gäller?",
  answer: "Gränsen är 700 000 kr.",
  completion_model: {
    id: "model-1",
    name: "claude-haiku-4-5",
    nickname: "Claude Haiku 4.5",
    litellm_model_name: "anthropic/claude-haiku-4-5",
    deployment_name: null
  },
  references: [
    { id: "blob-1", metadata: { title: "LOU 19 kap.", url: "https://riksdagen.se/lou" } },
    { id: "blob-2", metadata: { title: null, url: null } }
  ],
  mcp_tool_references: [{ id: "ref-1", uri: "mcp://files/a.md", mime_type: "text/markdown" }],
  files: [file("f-1", "Policy.pdf")],
  generated_files: [file("f-2", "Rapport.pdf")],
  tools: { assistants: [] },
  tool_calls: [
    {
      server_name: "lou",
      tool_name: "lou_troskelvarden",
      mcp_tool_name: "lou__troskelvarden",
      result_status: "succeeded",
      is_internal: false,
      meta: {
        "gen_ai.provider.name": "anthropic",
        "gen_ai.response.model": "claude-haiku-4-5",
        "gen_ai.usage.input_tokens": 120,
        "gen_ai.usage.output_tokens": 30
      }
    },
    {
      server_name: "skills",
      tool_name: "activate_skill",
      title: "Upphandlingsguide",
      is_internal: true,
      approved: false
    }
  ],
  num_tokens_question: 1200,
  num_tokens_answer: 300
} as unknown as PersistedMessage;

describe("projectTurnDebugDetails", () => {
  it("projects model, tokens, tools with usage, knowledge and files", () => {
    const details = projectTurnDebugDetails(message);
    expect(details.model).toEqual({
      id: "model-1",
      name: "claude-haiku-4-5",
      nickname: "Claude Haiku 4.5",
      route: "anthropic/claude-haiku-4-5"
    });
    expect(details.createdAt).toBe("2026-10-01T08:30:00Z");
    expect(details.inputTokens).toBe(1200);
    expect(details.outputTokens).toBe(300);

    expect(details.tools).toEqual([
      {
        order: 1,
        serverName: "lou",
        toolName: "lou__troskelvarden",
        isSkill: false,
        status: "succeeded",
        usage: {
          provider: "anthropic",
          model: "claude-haiku-4-5",
          inputTokens: 120,
          outputTokens: 30
        }
      },
      // A Skill activation is named by the Skill; a denied approval reads as rejected.
      {
        order: 2,
        serverName: "skills",
        toolName: "Upphandlingsguide",
        isSkill: true,
        status: "rejected",
        usage: null
      }
    ]);
    expect(details.knowledge).toEqual([
      { order: 1, title: "LOU 19 kap.", uri: "https://riksdagen.se/lou" },
      { order: 2, title: "blob-2", uri: null },
      { order: 3, title: "MCP", uri: "mcp://files/a.md" }
    ]);
    expect(details.files.map((entry) => [entry.order, entry.name, entry.kind])).toEqual([
      [1, "Policy.pdf", "input"],
      [2, "Rapport.pdf", "generated"]
    ]);
  });

  it("lets the activation evidence's model id and route win over the snapshot", () => {
    const details = projectTurnDebugDetails(message, { id: "model-9", route: "azure/haiku" });
    expect(details.model?.id).toBe("model-9");
    expect(details.model?.route).toBe("azure/haiku");
    expect(details.model?.name).toBe("claude-haiku-4-5");
  });

  it("copes with a bare legacy message", () => {
    const details = projectTurnDebugDetails({
      question: "?",
      answer: "!",
      references: [],
      files: [],
      generated_files: [],
      tools: { assistants: [] }
    } as unknown as PersistedMessage);
    expect(details.model).toBeNull();
    expect(details.tools).toEqual([]);
    expect(details.knowledge).toEqual([]);
    expect(details.files).toEqual([]);
    expect(details.inputTokens).toBe(0);
  });
});

describe("readToolUsage", () => {
  it("reads the GenAI attributes and ignores anything else", () => {
    expect(readToolUsage({ "gen_ai.request.model": "gpt-5", other: 1 })).toEqual({
      provider: null,
      model: "gpt-5",
      inputTokens: null,
      outputTokens: null
    });
    expect(readToolUsage({ other: 1 })).toBeNull();
    expect(readToolUsage(null)).toBeNull();
    expect(readToolUsage(["x"])).toBeNull();
  });
});

describe("listDebugTurns", () => {
  it("numbers the saved messages and skips ones without an id", () => {
    const turns = listDebugTurns([
      { ...message, id: "a", created_at: "2026-10-01T08:30:00Z" },
      { ...message, id: null },
      { ...message, id: "c", created_at: null }
    ]);
    expect(turns).toEqual([
      { messageId: "a", turnNumber: 1, createdAt: "2026-10-01T08:30:00Z" },
      { messageId: "c", turnNumber: 3, createdAt: null }
    ]);
  });
});

const reference = (key: string, position: number, source: "space" | "organization" = "space") => ({
  activation_key: key,
  skill_id: `skill-${key}`,
  skill_revision_id: `rev-${key}`,
  revision_number: 2,
  content_digest: `digest-${key}`,
  position,
  source,
  display_name: key.toUpperCase(),
  slug: key
});

const evidence: SkillActivationEvidence = {
  effective_mode: "selective",
  available: [reference("b", 1), reference("a", 0)],
  blocked: [reference("c", 2, "organization")],
  initially_active: ["a"],
  accepted: ["b"],
  repeated: ["b"],
  rejected: [
    { activation_key: "b", reason: "activation_limit_exceeded" },
    { activation_key: "zzz", reason: "unknown_key" }
  ],
  selected_model_id: "model-1",
  selected_model_route: "anthropic/claude-haiku-4-5",
  skill_context_tokens: 400,
  skill_context_token_limit: 1000,
  token_count_source: "litellm"
};

describe("skill activation evidence", () => {
  it("builds the candidate rows in evaluation order with their outcomes", () => {
    const rows = buildSkillActivationRows(evidence);
    expect(rows.map((row) => row.activationKey)).toEqual(["a", "b", "c"]);
    expect(rows[0]).toMatchObject({
      candidateState: "available",
      activationMode: "always",
      outcomes: [],
      rejectionReasons: []
    });
    expect(rows[1]).toMatchObject({
      activationMode: "on_demand",
      outcomes: ["accepted", "repeated", "rejected"],
      rejectionReasons: ["activation_limit_exceeded"]
    });
    expect(rows[2]).toMatchObject({
      candidateState: "blocked",
      activationMode: null,
      outcomes: ["blocked"]
    });
  });

  it("falls back to the revision id as the activation key", () => {
    const rows = buildSkillActivationRows({
      ...evidence,
      available: [{ ...reference("x", 0), activation_key: null }],
      blocked: [],
      initially_active: ["rev-x"],
      accepted: [],
      repeated: [],
      rejected: []
    });
    expect(rows[0]?.activationKey).toBe("rev-x");
    expect(rows[0]?.activationMode).toBe("always");
  });

  it("summarises what entered the context and lists rejections no candidate explains", () => {
    expect(summarizeSkillActivation(evidence)).toEqual({
      available: 2,
      enteredContext: 2,
      blocked: 1,
      rejected: 2
    });
    expect(unmatchedActivationRejections(evidence)).toEqual([
      { activation_key: "zzz", reason: "unknown_key" }
    ]);
  });
});
