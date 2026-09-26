import type { Schema } from "@/lib/api/models";
import { asString, hostOf } from "@/lib/chat/metadata";
import type { EneoUIMessage, KnowledgeOrigin } from "@/lib/chat/types";
import { mcpReferencesFromParts, mergeSources, type SourceChip } from "./message-parts";
import { eneoToolMetadata, isSkillCall } from "./tool-presentation";

/**
 * The activity of one assistant turn, derived from its message parts: the
 * ordered steps (reasoning, knowledge retrieval, tool calls, skills, writing
 * the answer), the numbered sources and a summary for the activity pill.
 * Pure data; the pill and the Aktivitet panel render it. Durations are not
 * part of the message data: they come from client measurements
 * (activity-timings.ts) and are only shown when known.
 */

type Part = EneoUIMessage["parts"][number];
export type ToolPart = Extract<Part, { type: "dynamic-tool" }>;
type McpReference = Schema<"McpToolReferencePublic">;

/** `stopped`: the turn ended (stopped or failed) before the step finished. */
export type StepStatus = "waiting" | "running" | "done" | "error" | "denied" | "stopped";

export type ActivityStep =
  | { kind: "reasoning"; key: string; status: StepStatus; text: string }
  | {
      kind: "knowledge";
      key: string;
      status: StepStatus;
      /** Number of retrieved documents. */
      hits: number;
      /** The collections/websites the hits came from (only those we can name). */
      origins: KnowledgeOrigin[];
    }
  | {
      kind: "tool";
      key: string;
      status: StepStatus;
      part: ToolPart;
      /** Approval record for tools that needed approval; null when none was needed. */
      approval: "approved" | "denied" | null;
      /** MCP resources this call read (documents with page ranges, pages). */
      references: McpReference[];
    }
  | { kind: "skill"; key: string; status: StepStatus; part: ToolPart }
  | {
      kind: "answer";
      key: string;
      status: StepStatus;
      model: string | null;
      tokens: number | null;
    };

export type ActivitySource = SourceChip & {
  /** Where the source lives: collection/website name or web host. */
  origin: string | null;
  /** The pages it was cited from, when the reference says ("4, 9"). */
  pageRange: string | null;
};

export type Activity = {
  steps: ActivityStep[];
  sources: ActivitySource[];
  /** True when there is something worth opening the panel for. */
  hasActivity: boolean;
  running: boolean;
  errorCount: number;
};

function eneoMetadata(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || !("eneo" in value)) return {};
  const eneo = (value as { eneo?: unknown }).eneo;
  return eneo && typeof eneo === "object" ? (eneo as Record<string, unknown>) : {};
}

function toolStatus(part: ToolPart): StepStatus {
  switch (part.state) {
    case "input-streaming":
    case "approval-requested":
      return "waiting";
    case "input-available":
    case "approval-responded":
      return "running";
    case "output-available":
      return "done";
    case "output-denied":
      return "denied";
    case "output-error":
      return part.errorText === "denied" || part.errorText === "timeout_denied"
        ? "denied"
        : "error";
    default:
      return "waiting";
  }
}

/** Approval decisions from the stream's approval parts and persisted tool calls. */
function approvals(parts: Part[]): Map<string, "approved" | "denied"> {
  const decisions = new Map<string, "approved" | "denied">();
  for (const part of parts) {
    if (part.type !== "data-tool-approval") continue;
    for (const tool of part.data.tools) {
      if (!tool.tool_call_id) continue;
      if (part.data.status === "timeout_denied" || tool.approved === false) {
        decisions.set(tool.tool_call_id, "denied");
      } else if (tool.approved === true) {
        decisions.set(tool.tool_call_id, "approved");
      }
    }
  }
  return decisions;
}

function toolApproval(
  part: ToolPart,
  decisions: Map<string, "approved" | "denied">
): "approved" | "denied" | null {
  const persisted = eneoToolMetadata(part).approved;
  if (persisted === true) return "approved";
  if (persisted === false) return "denied";
  return decisions.get(part.toolCallId) ?? null;
}

function sourceDocumentOrigin(part: Extract<Part, { type: "source-document" }>): {
  groupId: string | null;
  websiteId: string | null;
} {
  const eneo = eneoMetadata(part.providerMetadata);
  return { groupId: asString(eneo.group_id), websiteId: asString(eneo.website_id) };
}

function knowledgeStep(
  parts: Part[],
  knowledge: KnowledgeOrigin[]
): Extract<ActivityStep, { kind: "knowledge" }> | null {
  const documents = parts.filter(
    (part): part is Extract<Part, { type: "source-document" }> => part.type === "source-document"
  );
  if (documents.length === 0) return null;
  const byId = new Map(knowledge.map((origin) => [origin.id, origin]));
  const origins: KnowledgeOrigin[] = [];
  const seen = new Set<string>();
  for (const document of documents) {
    const { groupId, websiteId } = sourceDocumentOrigin(document);
    for (const id of [groupId, websiteId]) {
      const origin = id ? byId.get(id) : undefined;
      if (origin && !seen.has(origin.id)) {
        seen.add(origin.id);
        origins.push(origin);
      }
    }
  }
  return { kind: "knowledge", key: "knowledge", status: "done", hits: documents.length, origins };
}

/** The model that wrote an answer: its nickname, else its name. */
export function modelName(message: EneoUIMessage): string | null {
  const fromMetadata = message.metadata?.completionModel;
  if (fromMetadata) {
    return asString(fromMetadata.nickname) ?? asString(fromMetadata.name);
  }
  const session = message.parts.find((part) => part.type === "data-session");
  if (session?.type === "data-session" && session.data.completion_model) {
    const model = session.data.completion_model;
    return asString(model.nickname) ?? asString(model.name);
  }
  return null;
}

/** The sources of a message, numbered in citation order, with where they come from. */
function activitySources(
  message: EneoUIMessage,
  knowledge: KnowledgeOrigin[] = []
): ActivitySource[] {
  const mcpReferences = mcpReferencesFromParts(message.parts, message.metadata?.mcpToolReferences);
  const chips = mergeSources(message.parts, message.metadata?.webSearchReferences, mcpReferences);
  const byId = new Map(knowledge.map((origin) => [origin.id, origin.name]));
  const documents = new Map(
    message.parts
      .filter(
        (part): part is Extract<Part, { type: "source-document" }> =>
          part.type === "source-document"
      )
      .map((part) => [part.sourceId, sourceDocumentOrigin(part)])
  );
  return chips.map((chip) => {
    const document = documents.get(chip.sourceId);
    const knowledgeName = document
      ? (byId.get(document.groupId ?? "") ?? byId.get(document.websiteId ?? "") ?? null)
      : null;
    // A section is already part of an MCP source's title.
    const snippet = chip.mcpSnippet;
    return {
      ...chip,
      origin: knowledgeName ?? hostOf(chip.url) ?? hostOf(snippet?.uri) ?? null,
      pageRange: snippet?.pageRange ?? null
    };
  });
}

/**
 * Derives the activity for an assistant message. `streaming` marks the turn
 * that is still being generated (its last step is running).
 */
export function deriveActivity(
  message: EneoUIMessage,
  {
    streaming = false,
    knowledge = [],
    tokens = null
  }: { streaming?: boolean; knowledge?: KnowledgeOrigin[]; tokens?: number | null } = {}
): Activity {
  const parts = message.parts;
  const decisions = approvals(parts);
  const mcpReferences = mcpReferencesFromParts(parts, message.metadata?.mcpToolReferences);
  const steps: ActivityStep[] = [];

  const knowledgeRetrieval = knowledgeStep(parts, knowledge);
  if (knowledgeRetrieval) steps.push(knowledgeRetrieval);

  let reasoningIndex = 0;
  for (const part of parts) {
    if (part.type === "reasoning") {
      if (!part.text.trim() && part.state !== "streaming") continue;
      steps.push({
        kind: "reasoning",
        key: `reasoning-${reasoningIndex++}`,
        status: part.state === "streaming" ? "running" : "done",
        text: part.text
      });
    } else if (part.type === "dynamic-tool") {
      if (isSkillCall(part)) {
        steps.push({
          kind: "skill",
          key: `skill-${part.toolCallId}`,
          status: toolStatus(part),
          part
        });
      } else {
        steps.push({
          kind: "tool",
          key: `tool-${part.toolCallId}`,
          status: toolStatus(part),
          part,
          approval: toolApproval(part, decisions),
          references: mcpReferences.filter(
            (reference) =>
              reference.tool_call_id === part.toolCallId &&
              !(reference.mime_type ?? "").startsWith("image/")
          )
        });
      }
    }
  }

  const text = parts
    .filter((part) => part.type === "text")
    .map((part) => part.text)
    .join("");
  const lastPart = parts.at(-1);
  const writing = streaming && lastPart?.type === "text";
  const answerTokens = tokens ?? message.metadata?.tokens?.completion ?? null;
  if (text.trim() || writing) {
    steps.push({
      kind: "answer",
      key: "answer",
      status: writing ? "running" : streaming ? "waiting" : "done",
      model: modelName(message),
      tokens: answerTokens && answerTokens > 0 ? answerTokens : null
    });
  }

  // A finished turn has no running steps: whatever did not complete was cut off.
  if (!streaming) {
    for (const step of steps) {
      if (step.status === "running" || step.status === "waiting") step.status = "stopped";
    }
  }

  const sources = activitySources(message, knowledge);
  const meaningfulSteps = steps.filter((step) => step.kind !== "answer");
  const errorCount = steps.filter((step) => step.status === "error").length;
  return {
    steps,
    sources,
    hasActivity: meaningfulSteps.length > 0 || sources.length > 0,
    running: streaming,
    errorCount
  };
}

/** The step to name in the live pill while a turn streams: the last unfinished one. */
export function currentStep(activity: Activity): ActivityStep | null {
  if (!activity.running) return null;
  for (let index = activity.steps.length - 1; index >= 0; index--) {
    const step = activity.steps[index]!;
    if (step.status === "running" || step.status === "waiting") return step;
  }
  return activity.steps.at(-1) ?? null;
}
