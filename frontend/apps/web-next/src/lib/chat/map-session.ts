import type { Schema } from "@/lib/api/models";
import type { EneoUIMessage } from "./types";

type PersistedMessage = Schema<"Message">;

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
        tokens: { prompt: message.num_tokens_question }
      }
    });

    const parts: EneoUIMessage["parts"] = [];

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
        webSearchReferences: (message.web_search_references ?? []).map((ref) => ({
          id: String(ref.id),
          title: ref.title,
          url: ref.url
        })),
        tokens: {
          prompt: message.num_tokens_question,
          completion: message.num_tokens_answer
        },
        completionModel: message.completion_model
          ? {
              id: String(message.completion_model.id),
              name: message.completion_model.name,
              token_limit: message.completion_model.max_input_tokens
            }
          : null
      }
    });
  }

  return result;
}
