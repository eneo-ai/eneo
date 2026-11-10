import type { Schema } from "@/lib/api/models";
import type { EneoToolMetadata, EneoUIMessage, ToolAppView } from "./types";

type PersistedMessage = Schema<"Message">;

// ponytail: a time window; a turn status on the saved row if a turn ever outlives it.
const RUNNING_WINDOW_MS = 15 * 60_000;

/**
 * Whether a turn may still be answering: the core writes the question with an
 * empty answer before the model starts and updates the row when the turn
 * ends, however it ends. A row never updated is running, unless it is older
 * than any turn runs (it failed before the model started).
 */
function stillRunning(message: PersistedMessage, now: number): boolean {
  if (!message.created_at || message.updated_at !== message.created_at) return false;
  return now - Date.parse(message.created_at) < RUNNING_WINDOW_MS;
}

/**
 * Maps a persisted conversation (question/answer pairs) onto UIMessages so
 * useChat can render history with the same part renderers as live streams.
 *
 * Lenient by design: old sessions may carry partial or unknown data — map
 * what is recognized, ignore the rest, never throw.
 */
export function mapSessionMessages(
  messages: PersistedMessage[],
  now: number = Date.now()
): EneoUIMessage[] {
  const result: EneoUIMessage[] = [];

  for (const [index, message] of messages.entries()) {
    const baseId = message.id ?? `history-${index}`;
    // A turn that failed or was stopped before anything came back is saved
    // with an empty answer: the question stands alone, marked unanswered, so
    // the conversation shows no empty answer and offers "Försök igen". One
    // still running (in another tab) stands alone without the offer.
    const empty =
      !message.answer?.trim() &&
      !message.reasoning?.trim() &&
      (message.tool_calls ?? []).length === 0 &&
      (message.generated_files ?? []).length === 0;
    const unanswered = empty && !stillRunning(message, now);

    result.push({
      id: `${baseId}-q`,
      role: "user",
      parts: [{ type: "text", text: message.question ?? "" }],
      metadata: {
        files: message.files ?? [],
        tokens: { prompt: message.num_tokens_question },
        createdAt: message.created_at ?? null,
        ...(unanswered ? { unanswered: true } : {})
      }
    });
    if (empty) continue;

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
      parts.push({
        type: "dynamic-tool",
        toolName: tool.tool_name ?? "tool",
        toolCallId: tool.tool_call_id ?? `${baseId}-tool-${parts.length}`,
        providerMetadata: {
          eneo: {
            server_name: tool.server_name,
            title: tool.title ?? null,
            purpose: tool.purpose ?? null,
            // Eneo's own server or not, by the backend's routing (null before the flag existed).
            is_internal: tool.is_internal ?? null,
            is_bundled: tool.is_bundled ?? null,
            app_view: (tool.app_view as ToolAppView | null | undefined) ?? null,
            // Approval record for MCP tools that needed approval (null: none needed).
            approved: tool.approved ?? null,
            result_status: tool.result_status ?? null,
            // The files the call produced (live streams carry the call id on the file part).
            generated_file_ids: tool.generated_file_ids ?? null,
            // Data an own server's call returned (a flow run's id), kept in the history.
            structured_content: tool.structured_content ?? null
          } satisfies EneoToolMetadata
        },
        state:
          tool.result_status && tool.result_status !== "succeeded"
            ? "output-error"
            : "output-available",
        input: tool.arguments ?? {},
        output: { status: tool.result_status ?? "succeeded" },
        errorText:
          tool.result_status && tool.result_status !== "succeeded" ? tool.result_status : undefined
      } as EneoUIMessage["parts"][number]);
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
          completion: message.num_tokens_answer,
          contextPrompt: message.context_prompt_tokens ?? null,
          contextCompletion: message.context_completion_tokens ?? null
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
