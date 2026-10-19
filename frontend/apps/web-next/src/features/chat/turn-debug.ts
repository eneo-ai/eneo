import type { Schema } from "@/lib/api/models";
import { isSkillCall } from "./tool-presentation";

/**
 * What the Felsök tab shows for one saved chat turn, projected from the
 * persisted message (GET /conversations/{id}/) and the turn's body-free
 * diagnostics (GET …/messages/{id}/diagnostics/). Ported from the Svelte
 * app's turnDebugProjection.ts and skillActivationDebug.ts; pure so the
 * panel stays presentation only.
 */

export type PersistedMessage = Schema<"Message">;
export type ChatTurnDiagnostics = Schema<"ChatTurnDiagnostics">;
export type SkillActivationEvidence = Schema<"SkillActivationEvidenceV1">;
export type SkillActivationReference = Schema<"SkillActivationReference">;
export type SkillActivationRejection = Schema<"SkillActivationRejection">;

export type DebugTurn = { messageId: string; turnNumber: number; createdAt: string | null };

/**
 * Usage a model-backed tool reported for its own provider call, read from the
 * OpenTelemetry GenAI attributes (`gen_ai.*`) on the tool result's MCP `_meta`.
 */
export type ToolDebugUsage = {
  provider: string | null;
  model: string | null;
  inputTokens: number | null;
  outputTokens: number | null;
};

export type TurnDebugTool = {
  order: number;
  serverName: string;
  toolName: string;
  /** A Skill activation step (named by the Skill) rather than a server call. */
  isSkill: boolean;
  status: string | null;
  usage: ToolDebugUsage | null;
};

export type TurnDebugDetails = {
  model: { id: string; name: string; nickname: string | null; route: string } | null;
  createdAt: string | null;
  inputTokens: number;
  outputTokens: number;
  tools: TurnDebugTool[];
  knowledge: { order: number; title: string; uri: string | null }[];
  files: {
    order: number;
    id: string;
    name: string;
    mimetype: string;
    size: number;
    kind: "input" | "generated";
  }[];
};

function metaString(meta: Record<string, unknown>, key: string): string | null {
  const value = meta[key];
  return typeof value === "string" && value.length > 0 ? value : null;
}

function metaCount(meta: Record<string, unknown>, key: string): number | null {
  const value = meta[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function readToolUsage(meta: unknown): ToolDebugUsage | null {
  if (!meta || typeof meta !== "object" || Array.isArray(meta)) return null;
  const record = meta as Record<string, unknown>;
  const usage: ToolDebugUsage = {
    provider: metaString(record, "gen_ai.provider.name"),
    model:
      metaString(record, "gen_ai.response.model") ?? metaString(record, "gen_ai.request.model"),
    inputTokens: metaCount(record, "gen_ai.usage.input_tokens"),
    outputTokens: metaCount(record, "gen_ai.usage.output_tokens")
  };
  return Object.values(usage).some((value) => value !== null) ? usage : null;
}

/** The saved turns of a conversation that can be inspected, in order. */
export function listDebugTurns(messages: PersistedMessage[]): DebugTurn[] {
  const turns: DebugTurn[] = [];
  for (const [index, message] of messages.entries()) {
    if (!message.id) continue;
    turns.push({
      messageId: message.id,
      turnNumber: index + 1,
      createdAt: message.created_at ?? null
    });
  }
  return turns;
}

export type TurnDebugModelFallback = { id: string; route: string };

export function projectTurnDebugDetails(
  message: PersistedMessage,
  modelFallback?: TurnDebugModelFallback
): TurnDebugDetails {
  const tools = (message.tool_calls ?? []).map((tool, index): TurnDebugTool => {
    const skill = isSkillCall({ toolName: tool.tool_name, providerMetadata: { eneo: tool } });
    return {
      order: index + 1,
      serverName: tool.server_name,
      // A Skill activation is more useful by Skill name than by the internal
      // activation tool identifier.
      toolName: skill ? (tool.title ?? tool.tool_name) : (tool.mcp_tool_name ?? tool.tool_name),
      isSkill: skill,
      status:
        tool.result_status ??
        (tool.approved === false ? "rejected" : tool.approved === true ? "approved" : null),
      usage: readToolUsage(tool.meta)
    };
  });

  const knowledge: TurnDebugDetails["knowledge"] = [];
  for (const reference of message.references ?? []) {
    knowledge.push({
      order: knowledge.length + 1,
      title: reference.metadata?.title ?? reference.metadata?.url ?? reference.id,
      uri: reference.metadata?.url ?? null
    });
  }
  for (const reference of message.mcp_tool_references ?? []) {
    knowledge.push({ order: knowledge.length + 1, title: "MCP", uri: reference.uri ?? null });
  }

  // The activation evidence records the id and route LiteLLM actually used,
  // so when it is present it wins over the model snapshot on the message;
  // the snapshot still provides the human-readable display name.
  const completionModel = message.completion_model;
  const model =
    completionModel || modelFallback
      ? {
          id: modelFallback?.id ?? completionModel!.id,
          name: completionModel?.name ?? modelFallback!.route,
          nickname: completionModel?.nickname ?? null,
          route:
            modelFallback?.route ??
            completionModel!.litellm_model_name ??
            completionModel!.deployment_name ??
            completionModel!.name
        }
      : null;

  const files = message.files ?? [];
  const generated = message.generated_files ?? [];
  return {
    createdAt: message.created_at ?? null,
    model,
    inputTokens: message.num_tokens_question ?? 0,
    outputTokens: message.num_tokens_answer ?? 0,
    tools,
    knowledge,
    files: [
      ...files.map((file, index) => ({
        order: index + 1,
        id: file.id,
        name: file.name,
        mimetype: file.mimetype,
        size: file.size,
        kind: "input" as const
      })),
      ...generated.map((file, index) => ({
        order: files.length + index + 1,
        id: file.id,
        name: file.name,
        mimetype: file.mimetype,
        size: file.size,
        kind: "generated" as const
      }))
    ]
  };
}

// ---------------------------------------------------------------------------
// Skill activation evidence
// ---------------------------------------------------------------------------

export type SkillActivationOutcome = "accepted" | "repeated" | "blocked" | "rejected";

export type SkillActivationRow = SkillActivationReference & {
  activationKey: string;
  candidateState: "available" | "blocked";
  activationMode: "always" | "on_demand" | null;
  outcomes: SkillActivationOutcome[];
  rejectionReasons: SkillActivationRejection["reason"][];
};

/** Every candidate Skill of the turn in evaluation order, with what happened to it. */
export function buildSkillActivationRows(evidence: SkillActivationEvidence): SkillActivationRow[] {
  const initiallyActive = new Set(evidence.initially_active);
  const accepted = new Set(evidence.accepted ?? []);
  const repeated = new Set(evidence.repeated ?? []);
  const blocked = new Set(
    evidence.blocked.map((reference) => reference.activation_key ?? reference.skill_revision_id)
  );
  const rejectionReasons = new Map<string, SkillActivationRejection["reason"][]>();
  for (const rejection of evidence.rejected ?? []) {
    const reasons = rejectionReasons.get(rejection.activation_key) ?? [];
    reasons.push(rejection.reason);
    rejectionReasons.set(rejection.activation_key, reasons);
  }

  return [
    ...evidence.available.map((reference) => ({ reference, candidateState: "available" as const })),
    ...evidence.blocked.map((reference) => ({ reference, candidateState: "blocked" as const }))
  ]
    .sort((left, right) => left.reference.position - right.reference.position)
    .map(({ reference, candidateState }) => {
      const activationKey = reference.activation_key ?? reference.skill_revision_id;
      const outcomes: SkillActivationOutcome[] = [];
      if (accepted.has(activationKey)) outcomes.push("accepted");
      if (repeated.has(activationKey)) outcomes.push("repeated");
      if (blocked.has(activationKey)) outcomes.push("blocked");
      if (rejectionReasons.has(activationKey)) outcomes.push("rejected");
      return {
        ...reference,
        activationKey,
        candidateState,
        activationMode:
          candidateState === "blocked"
            ? null
            : initiallyActive.has(activationKey)
              ? "always"
              : "on_demand",
        outcomes,
        rejectionReasons: rejectionReasons.get(activationKey) ?? []
      };
    });
}

export function summarizeSkillActivation(evidence: SkillActivationEvidence) {
  const enteredContext = new Set([...evidence.initially_active, ...(evidence.accepted ?? [])]);
  return {
    available: evidence.available.length,
    enteredContext: enteredContext.size,
    blocked: evidence.blocked.length,
    rejected: evidence.rejected?.length ?? 0
  };
}

/** Rejections whose activation key matches no candidate of the turn. */
export function unmatchedActivationRejections(
  evidence: SkillActivationEvidence
): SkillActivationRejection[] {
  const knownKeys = new Set(
    [...evidence.available, ...evidence.blocked].map(
      (reference) => reference.activation_key ?? reference.skill_revision_id
    )
  );
  return (evidence.rejected ?? []).filter((rejection) => !knownKeys.has(rejection.activation_key));
}
