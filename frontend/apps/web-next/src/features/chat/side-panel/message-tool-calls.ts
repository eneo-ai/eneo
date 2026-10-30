import type { EneoFileMetadata, EneoToolMetadata, EneoUIMessage } from "@/lib/chat/types";
import { eneoToolMetadata } from "../tool-presentation";

type Part = EneoUIMessage["parts"][number];
export type ToolPart = Extract<Part, { type: "dynamic-tool" }>;
type FilePart = Extract<Part, { type: "file" }>;

/**
 * A tool call of a message as the panel reads it, the same whether the
 * message is being streamed or came from history: the part's own state and
 * input, and the Eneo metadata the backend put on it.
 */
export type ToolCallRecord = {
  toolCallId: string;
  toolName: string;
  state: ToolPart["state"];
  /** The arguments, complete or as far as the model has written them. */
  input: Record<string, unknown> | undefined;
  serverName: string | null;
  title: string | null;
  purpose: string | null;
  isInternal: boolean | null;
  isBundled: boolean;
  appView: EneoToolMetadata["app_view"] | null;
  approved: boolean | null;
  resultStatus: string | null;
  /** The files the call produced: recorded on the call in history, read from the file parts live. */
  generatedFileIds: string[];
  /** Data a call on one of Eneo's own servers returned (a flow run's id); null for others. */
  structuredContent: Record<string, unknown> | null;
  part: ToolPart;
};

/** A file the assistant created in an answer; `toolCallId` names the call that made it. */
export type GeneratedFile = EneoFileMetadata & { toolCallId: string | null };

function inputOf(part: ToolPart): Record<string, unknown> | undefined {
  return part.input && typeof part.input === "object" && !Array.isArray(part.input)
    ? (part.input as Record<string, unknown>)
    : undefined;
}

const asString = (value: unknown) => (typeof value === "string" ? value : null);
const asBoolean = (value: unknown) => (typeof value === "boolean" ? value : null);

/** The files of an answer: persisted on the message, or streamed as file parts. */
export function messageGeneratedFiles(message: EneoUIMessage): GeneratedFile[] {
  const files = new Map<string, GeneratedFile>();
  for (const file of message.metadata?.generatedFiles ?? []) {
    files.set(file.id, { ...file, toolCallId: null });
  }
  for (const part of message.parts) {
    if (part.type !== "file") continue;
    const eneo = (part as FilePart).providerMetadata?.eneo as Partial<EneoFileMetadata> | undefined;
    if (!eneo?.id || typeof eneo.name !== "string") continue;
    files.set(eneo.id, {
      ...(eneo as EneoFileMetadata),
      mimetype: eneo.mimetype ?? part.mediaType,
      size: eneo.size ?? 0,
      toolCallId: asString(eneo.tool_call_id)
    });
  }
  return [...files.values()];
}

/** The tool calls of an answer, in call order. */
export function messageToolCalls(message: EneoUIMessage): ToolCallRecord[] {
  if (message.role !== "assistant") return [];
  const filesByCall = new Map<string, string[]>();
  for (const file of messageGeneratedFiles(message)) {
    if (!file.toolCallId) continue;
    filesByCall.set(file.toolCallId, [...(filesByCall.get(file.toolCallId) ?? []), file.id]);
  }
  const calls: ToolCallRecord[] = [];
  for (const part of message.parts) {
    if (part.type !== "dynamic-tool") continue;
    const eneo = eneoToolMetadata(part) as EneoToolMetadata;
    const recorded = Array.isArray(eneo.generated_file_ids)
      ? eneo.generated_file_ids.filter((id): id is string => typeof id === "string")
      : [];
    calls.push({
      toolCallId: part.toolCallId,
      toolName: part.toolName,
      state: part.state,
      input: inputOf(part),
      serverName: asString(eneo.server_name),
      title: asString(eneo.title),
      purpose: asString(eneo.purpose),
      isInternal: asBoolean(eneo.is_internal),
      isBundled: eneo.is_bundled === true,
      appView: eneo.app_view ?? null,
      approved: asBoolean(eneo.approved),
      resultStatus:
        asString(eneo.result_status) ??
        (part.state === "output-available"
          ? "succeeded"
          : part.state === "output-error"
            ? (part.errorText ?? "failed")
            : null),
      generatedFileIds: [...new Set([...recorded, ...(filesByCall.get(part.toolCallId) ?? [])])],
      structuredContent:
        eneo.structured_content && typeof eneo.structured_content === "object"
          ? eneo.structured_content
          : null,
      part
    });
  }
  return calls;
}

/**
 * The messages with `file`, a version a reader saved of a document, added to
 * the answer that holds the version it was edited from (the last answer when
 * none does), as the backend has stored it. The messages are unchanged when
 * the file is already there.
 */
export function addGeneratedFile(
  messages: EneoUIMessage[],
  file: EneoFileMetadata & { revises_file_id?: string | null }
): EneoUIMessage[] {
  const holds = (message: EneoUIMessage, id: string) =>
    messageGeneratedFiles(message).some((other) => other.id === id);
  const holder =
    messages.find((message) => !!file.revises_file_id && holds(message, file.revises_file_id)) ??
    messages.findLast((message) => message.role === "assistant");
  if (!holder || holds(holder, file.id)) return messages;
  return messages.map((message) =>
    message === holder
      ? {
          ...message,
          metadata: {
            ...message.metadata,
            generatedFiles: [...(message.metadata?.generatedFiles ?? []), file]
          }
        }
      : message
  );
}
