import type { Schema } from "@/lib/api/models";
import type { EneoToolMetadata, EneoUIMessage, ToolAppView } from "./types";

type PersistedMessage = Schema<"Message">;
type RecordedTool = NonNullable<PersistedMessage["tool_calls"]>[number];
type ToolPart = Extract<EneoUIMessage["parts"][number], { type: "dynamic-tool" }>;

/** The result endpoint uses a specialist's step UUID, even when two providers reuse a call ID. */
export function recordedToolPart(
  tool: RecordedTool,
  resultId: string,
  pending?: "input-available" | "input-streaming"
): ToolPart {
  const base = {
    type: "dynamic-tool" as const,
    toolName: tool.tool_name,
    toolCallId: resultId,
    providerMetadata: {
      eneo: {
        server_name: tool.server_name,
        title: tool.title ?? null,
        purpose: tool.purpose ?? null,
        is_internal: tool.is_internal ?? null,
        is_bundled: tool.is_bundled ?? null,
        app_view: (tool.app_view as ToolAppView | null | undefined) ?? null,
        approved: tool.approved ?? null,
        result_status: tool.result_status ?? null,
        generated_file_ids: tool.generated_file_ids ?? null
      } satisfies EneoToolMetadata
    },
    input: tool.arguments ?? {}
  };
  if (tool.approved === false) return { ...base, state: "output-error", errorText: "denied" };
  if (pending) return { ...base, state: pending };
  if (tool.result_status && !["succeeded", "completed"].includes(tool.result_status)) {
    return { ...base, state: "output-error", errorText: tool.result_status };
  }
  return {
    ...base,
    state: "output-available",
    output: { status: tool.result_status ?? "succeeded" }
  };
}

/**
 * Maps a persisted conversation (question/answer pairs) onto UIMessages so
 * useChat can render history with the same part renderers as live streams.
 *
 * Lenient by design: old sessions may carry partial or unknown data — map
 * what is recognized, ignore the rest, never throw.
 */
export function mapSessionMessages(messages: PersistedMessage[]): EneoUIMessage[] {
  const result: EneoUIMessage[] = [];

  for (const [index, message] of messages.entries()) {
    const baseId = message.id ?? `history-${index}`;

    result.push({
      id: `${baseId}-q`,
      role: "user",
      parts: [{ type: "text", text: message.question ?? "" }],
      metadata: {
        files: message.files ?? [],
        tokens: { prompt: message.num_tokens_question },
        createdAt: message.created_at ?? null
      }
    });

    const parts: EneoUIMessage["parts"] = [];

    // Reasoning precedes the answer in a live stream; mirror that ordering so
    // the history renders the same collapsed trace above the text.
    if (message.reasoning?.trim()) {
      parts.push({ type: "reasoning", text: message.reasoning, state: "done" });
    }

    for (const reference of message.references ?? []) {
      if (!reference?.id) continue;
      parts.push({
        type: "source-document",
        sourceId: String(reference.id),
        mediaType: "text/plain",
        title: reference.metadata?.title ?? "",
        providerMetadata: { eneo: reference as unknown as Record<string, never> }
      });
    }

    for (const tool of message.tool_calls ?? []) {
      parts.push(recordedToolPart(tool, tool.tool_call_id ?? `${baseId}-tool-${parts.length}`));
    }

    for (const step of message.consultations ?? []) {
      // A reopened conversation cannot resume an interrupted specialist or its approval.
      const data =
        step.status === "running" || step.status === "awaiting_approval"
          ? { ...step, status: "incomplete" as const }
          : step;
      parts.push({ type: "data-consultation", id: step.id, data });
    }

    parts.push({ type: "text", text: message.answer ?? "" });

    result.push({
      id: baseId,
      role: "assistant",
      parts,
      metadata: {
        generatedFiles: message.generated_files ?? [],
        mcpToolReferences: message.mcp_tool_references ?? [],
        tokens: {
          prompt: message.num_tokens_question,
          completion: message.num_tokens_answer
        },
        completionModel: message.completion_model
          ? {
              id: String(message.completion_model.id),
              name: message.completion_model.name,
              nickname: message.completion_model.nickname ?? null,
              token_limit: message.completion_model.max_input_tokens
            }
          : null,
        answeringAssistant: message.tools?.assistants?.[0]
          ? {
              id: String(message.tools.assistants[0].id),
              handle: message.tools.assistants[0].handle
            }
          : null,
        createdAt: message.updated_at ?? message.created_at ?? null,
        feedback: message.feedback?.value ?? null
      }
    });
  }

  return result;
}
