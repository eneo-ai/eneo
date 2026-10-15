import type { ConversationMessage } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";
import { isSkillActivation } from "./internalToolLabels";

export type DebugTurnOption = {
  messageId: string;
  turnNumber: number;
  createdAt: string | null;
};

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

/**
 * Usage a digest tool reported for its reader model (`eneo.reader.*` on the
 * tool result's `_meta`): the model that read the material part by part, apart
 * from the turn's model that wrote the answer. Never part of the message's own
 * token counts.
 */
export type ReaderDebugUsage = {
  model: string;
  inputTokens: number;
  outputTokens: number;
};

export type TurnDebugDetails = {
  model: { id: string; name: string; route: string } | null;
  createdAt: string | null;
  inputTokens: number;
  outputTokens: number;
  /** The reader models' spend over every tool call of the turn, when any. */
  readerUsage: ReaderDebugUsage | null;
  tools: Array<{
    order: number;
    serverName: string;
    toolName: string;
    status: string | null;
    usage: ToolDebugUsage | null;
    readerUsage: ReaderDebugUsage | null;
  }>;
  knowledge: Array<{
    order: number;
    title: string;
    uri: string | null;
  }>;
  files: Array<{
    order: number;
    id: string;
    name: string;
    mimetype: string;
    size: number;
    kind: "input" | "generated";
  }>;
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

export function readReaderUsage(meta: unknown): ReaderDebugUsage | null {
  if (!meta || typeof meta !== "object" || Array.isArray(meta)) return null;
  const record = meta as Record<string, unknown>;
  const model = metaString(record, "eneo.reader.model");
  const inputTokens = metaCount(record, "eneo.reader.input_tokens");
  const outputTokens = metaCount(record, "eneo.reader.output_tokens");
  if (model === null || inputTokens === null || outputTokens === null) return null;
  return { model, inputTokens, outputTokens };
}

function sumReaderUsage(usages: Array<ReaderDebugUsage | null>): ReaderDebugUsage | null {
  const present = usages.filter((usage): usage is ReaderDebugUsage => usage !== null);
  if (present.length === 0) return null;
  const models = [...new Set(present.map((usage) => usage.model))];
  return {
    model: models.join(", "),
    inputTokens: present.reduce((sum, usage) => sum + usage.inputTokens, 0),
    outputTokens: present.reduce((sum, usage) => sum + usage.outputTokens, 0)
  };
}

type StreamingConversationMessage = ConversationMessage & {
  mcp_tool_calls?: NonNullable<ConversationMessage["tool_calls"]>;
};

export type TurnDebugModelFallback = {
  id: string;
  route: string;
};

export function listPersistedDebugTurns(
  messages: ConversationMessage[],
  pendingMessageIds: readonly string[]
): DebugTurnOption[] {
  const turns: DebugTurnOption[] = [];

  for (let index = 0; index < messages.length; index += 1) {
    const message = messages[index];
    if (!message.id || pendingMessageIds.includes(message.id)) continue;
    turns.push({
      messageId: message.id,
      turnNumber: index + 1,
      createdAt: message.created_at ?? null
    });
  }

  return turns;
}

export function projectTurnDebugDetails(
  message: ConversationMessage,
  modelFallback?: TurnDebugModelFallback
): TurnDebugDetails {
  const streamingToolCalls = (message as StreamingConversationMessage).mcp_tool_calls;
  const tools = (streamingToolCalls ?? message.tool_calls ?? []).map((tool, index) => ({
    order: index + 1,
    serverName: isSkillActivation(tool) ? m.skills() : tool.server_name,
    // A Skill activation is more useful by Skill name than by the internal
    // activation tool identifier.
    toolName: isSkillActivation(tool)
      ? `Skill · ${tool.title ?? tool.tool_name}`
      : (tool.mcp_tool_name ?? tool.tool_name),
    status:
      tool.result_status ??
      (tool.approved === false ? "rejected" : tool.approved === true ? "approved" : null),
    usage: readToolUsage(tool.meta),
    readerUsage: readReaderUsage(tool.meta)
  }));

  const knowledge: TurnDebugDetails["knowledge"] = [];
  for (const reference of message.references) {
    knowledge.push({
      order: knowledge.length + 1,
      title: reference.metadata.title ?? reference.metadata.url ?? reference.id,
      uri: reference.metadata.url ?? null
    });
  }
  for (const _reference of message.mcp_tool_references ?? []) {
    knowledge.push({
      order: knowledge.length + 1,
      title: "MCP",
      uri: null
    });
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
          route:
            modelFallback?.route ??
            completionModel!.litellm_model_name ??
            completionModel!.deployment_name ??
            completionModel!.name
        }
      : null;

  return {
    createdAt: message.created_at ?? null,
    model,
    inputTokens: message.num_tokens_question ?? 0,
    outputTokens: message.num_tokens_answer ?? 0,
    readerUsage: sumReaderUsage(tools.map((tool) => tool.readerUsage)),
    tools,
    knowledge,
    files: [
      ...message.files.map((file, index) => ({
        order: index + 1,
        id: file.id,
        name: file.name,
        mimetype: file.mimetype,
        size: file.size,
        kind: "input" as const
      })),
      ...message.generated_files.map((file, index) => ({
        order: message.files.length + index + 1,
        id: file.id,
        name: file.name,
        mimetype: file.mimetype,
        size: file.size,
        kind: "generated" as const
      }))
    ]
  };
}
