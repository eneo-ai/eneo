import { Brain, Eye, Wrench } from "lucide-react";
import { useTranslations } from "use-intl";
import { Button as RetryButton } from "@astryxdesign/core/Button";
import { ModelSelector } from "@/components/ai-elements/model-selector";
import { useAppContext } from "@/components/providers/app-context";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { Badge } from "@/components/ui/badge";
import { formatCostPerMillionTokens, formatTokens } from "@/features/ai-models/format-model-stats";
import { useSpace } from "@/features/spaces/use-space";
import type { Schema } from "@/lib/api/models";
import {
  effectiveAssistantModels,
  isModelsEnforced,
  lockedAssistantModel
} from "./effective-config";
import { ModelKwargsRows } from "./model-kwargs-rows";
import type { Assistant } from "./use-assistant";
import type { AssistantAiDraft } from "./use-assistant-ai-draft";
type CompletionModel = Schema<"CompletionModelPublic">;
function ModelSummary({
  model,
  showPricing,
  t
}: {
  model: CompletionModel;
  showPricing: boolean;
  t: (key: string, values?: Record<string, string>) => string;
}) {
  const inputPrice = formatCostPerMillionTokens(model.input_cost_per_token);
  const outputPrice = formatCostPerMillionTokens(model.output_cost_per_token);

  return (
    <div className="flex flex-wrap gap-1.5">
      {model.max_input_tokens > 0 && (
        <Badge variant="secondary" className="font-normal tabular-nums">
          {formatTokens(model.max_input_tokens)} {t("context_window")}
        </Badge>
      )}
      {model.vision && (
        <Badge variant="secondary" className="font-normal">
          <Eye aria-hidden="true" className="size-3" />
          {t("model_label_vision")}
        </Badge>
      )}
      {model.supports_tool_calling && (
        <Badge variant="secondary" className="font-normal">
          <Wrench aria-hidden="true" className="size-3" />
          {t("model_label_tool_calling")}
        </Badge>
      )}
      {model.reasoning && (
        <Badge variant="secondary" className="font-normal">
          <Brain aria-hidden="true" className="size-3" />
          {t("model_label_reasoning")}
        </Badge>
      )}
      {showPricing && inputPrice && (
        <Badge variant="outline" className="font-normal tabular-nums">
          {t("model_selector_input_price")}: {inputPrice}
        </Badge>
      )}
      {showPricing && outputPrice && (
        <Badge variant="outline" className="font-normal tabular-nums">
          {t("model_selector_output_price")}: {outputPrice}
        </Badge>
      )}
    </div>
  );
}

export function AiSection({ assistant, draft }: { assistant: Assistant; draft: AssistantAiDraft }) {
  const t = useTranslations();
  const { space } = useSpace();
  const { tenant } = useAppContext();
  const { modelId, kwargs, model, persist, changeModel, changeKwargs } = draft;
  const modelsEnforced = isModelsEnforced(assistant.effective_config);
  const availableModels = effectiveAssistantModels(
    space.completion_models,
    assistant.effective_config
  );
  const lockedModel = lockedAssistantModel(space.completion_models, assistant.effective_config);
  const lockedSummaryModel =
    space.completion_models.find((candidate) => candidate.id === lockedModel?.id) ?? null;
  const showModelPricing = tenant.show_model_pricing ?? false;
  return (
    <SettingsGroup title={t("ai_settings")}>
      <SettingsRow
        title={t("completion_model")}
        description={t("this_model_will_be_used")}
        htmlFor="assistant-completion-model"
      >
        <ModelSelector
          id="assistant-completion-model"
          models={availableModels}
          selectedId={modelId}
          onSelect={changeModel}
          locked={lockedModel}
          className="w-full justify-between"
          showPricing={showModelPricing}
        />
        {modelsEnforced && (
          <p className="text-muted-foreground text-xs">
            {t(
              lockedModel
                ? "governance_assistant_locked_by_policy"
                : "governance_assistant_models_filtered_hint"
            )}
          </p>
        )}
        {draft.isError && (
          <RetryButton label={t("retry")} onClick={() => void persist(modelId, kwargs)} />
        )}
        {(lockedSummaryModel ?? model) && (
          <ModelSummary
            model={(lockedSummaryModel ?? model)!}
            showPricing={showModelPricing}
            t={t}
          />
        )}
      </SettingsRow>
      <ModelKwargsRows
        idPrefix="assistant"
        model={model}
        kwargs={kwargs}
        behaviourDescription={t("select_preset_behavior")}
        onChange={(next, commit) => changeKwargs(next, commit)}
        onCommit={() => void persist(modelId, kwargs)}
      />
    </SettingsGroup>
  );
}
