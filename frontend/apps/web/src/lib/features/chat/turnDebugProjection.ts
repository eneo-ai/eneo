import type { ConversationMessage } from "@eneo/eneo-js";

export type DebugTurnOption = {
  messageId: string;
  turnNumber: number;
  questionExcerpt: string;
};

export type TurnDebugDetails = {
  model: { id: string; name: string; route: string } | null;
  inputTokens: number;
  outputTokens: number;
  tools: Array<{
    order: number;
    serverName: string;
    toolName: string;
    status: string | null;
  }>;
  knowledge: Array<{
    order: number;
    title: string;
    uri: string | null;
  }>;
  files: Array<{
    order: number;
    name: string;
    kind: "input" | "generated";
  }>;
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
      questionExcerpt: excerpt(message.question)
    });
  }

  return turns;
}

export function projectTurnDebugDetails(message: ConversationMessage): TurnDebugDetails {
  const tools = (message.tool_calls ?? []).map((tool, index) => ({
    order: index + 1,
    serverName: tool.server_name,
    toolName: tool.mcp_tool_name ?? tool.tool_name,
    status:
      tool.result_status ??
      (tool.approved === false ? "rejected" : tool.approved === true ? "approved" : null)
  }));

  const knowledge: TurnDebugDetails["knowledge"] = [];
  for (const reference of message.references) {
    knowledge.push({
      order: knowledge.length + 1,
      title: reference.metadata.title ?? reference.metadata.url ?? reference.id,
      uri: reference.metadata.url ?? null
    });
  }
  for (const reference of message.web_search_references) {
    knowledge.push({
      order: knowledge.length + 1,
      title: reference.title,
      uri: reference.url
    });
  }
  for (const reference of message.mcp_tool_references ?? []) {
    const title = reference.meta?.title;
    knowledge.push({
      order: knowledge.length + 1,
      title: typeof title === "string" && title.trim() ? title : reference.uri,
      uri: reference.uri
    });
  }

  return {
    model: message.completion_model
      ? {
          id: message.completion_model.id,
          name: message.completion_model.name,
          route:
            message.completion_model.litellm_model_name ??
            message.completion_model.deployment_name ??
            message.completion_model.name
        }
      : null,
    inputTokens: message.num_tokens_question ?? 0,
    outputTokens: message.num_tokens_answer ?? 0,
    tools,
    knowledge,
    files: [
      ...message.files.map((file, index) => ({
        order: index + 1,
        name: file.name,
        kind: "input" as const
      })),
      ...message.generated_files.map((file, index) => ({
        order: message.files.length + index + 1,
        name: file.name,
        kind: "generated" as const
      }))
    ]
  };
}

function excerpt(question: string): string {
  const singleLine = question.replace(/\s+/g, " ").trim();
  if (singleLine.length <= 72) return singleLine;
  return `${singleLine.slice(0, 69).trimEnd()}...`;
}
