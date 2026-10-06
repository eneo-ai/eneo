import { selectEffectiveModelId } from "@/features/ai-models/select-effective-chat-model";
import type { Schema } from "@/lib/api/models";
import type { ChatPartner } from "@/lib/chat/types";

type SparseModel = Schema<"CompletionModelSparse">;
type Catalog = { id: string; supports_tool_calling?: boolean | null }[];

/**
 * The completion model a partner answers with, as the chat shows it. Honours
 * the governance policy the way the backend does at ask time: an enforced
 * policy swaps a disallowed pick for its default or locked model. The
 * tool-calling flag is read from the space catalog entry when the space is
 * known, since the sparse model on the assistant may be stale, so tool
 * surfaces (use-tool-choices.ts) never see a missing flag by accident.
 */
export function partnerCompletionModel(
  assistant: {
    completion_model?: SparseModel | null;
    effective_config?: Schema<"EffectiveConfigPublic"> | null;
  },
  catalog: Catalog = []
): ChatPartner["completionModel"] {
  const config = assistant.effective_config ?? null;
  const effectiveId = selectEffectiveModelId(assistant.completion_model?.id, config);
  const policyModels = config
    ? [config.locked_model, config.default_model, ...config.available_models]
    : [];
  const model =
    (assistant.completion_model?.id === effectiveId ? assistant.completion_model : null) ??
    policyModels.find((candidate) => candidate?.id === effectiveId) ??
    assistant.completion_model;
  if (!model) return null;
  const supportsToolCalling =
    catalog.find((candidate) => candidate.id === model.id)?.supports_tool_calling ??
    model.supports_tool_calling;
  return {
    id: model.id,
    name: model.name,
    token_limit: model.max_input_tokens,
    vision: model.vision,
    reasoning: model.reasoning,
    supports_tool_calling: supportsToolCalling === true
  };
}
