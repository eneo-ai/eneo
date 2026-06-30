"use client";

import { Brain, Eye, Wrench } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ModelSelector } from "@/components/ai-elements/model-selector";
import { useAppContext } from "@/components/providers/app-context";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAutosave } from "@/components/composites/use-autosave";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { formatCostPerMillionTokens, formatTokens } from "@/features/ai-models/format-model-stats";
import { useSpace } from "@/features/spaces/use-space";
import type { Schema } from "@/lib/api/models";
import { cn } from "@/lib/utils";
import {
  BEHAVIOUR_LIST,
  behaviourFromKwargs,
  filterSupportedKwargs,
  isSelectKwarg,
  kwargCapability,
  kwargsForBehaviour,
  modelSpecificKwargs,
  supportsBehaviorPresets,
  type ModelBehaviour,
  type ModelKwargName,
  type ModelKwargs
} from "./model-kwargs";
import { useUpdateAssistant, type Assistant } from "./use-assistant";

type CompletionModel = Schema<"CompletionModelPublic">;

const NUMERIC_DEFAULT_MAX: Partial<Record<ModelKwargName, number>> = {
  top_p: 1,
  presence_penalty: 2,
  frequency_penalty: 2,
  top_k: 100
};

function kwargLabel(name: ModelKwargName, t: (key: string) => string): string {
  switch (name) {
    case "reasoning_effort":
      return t("reasoning_effort");
    case "verbosity":
      return t("verbosity");
    case "top_p":
      return t("top_p");
    case "presence_penalty":
      return t("presence_penalty");
    case "frequency_penalty":
      return t("frequency_penalty");
    case "top_k":
      return t("top_k");
    default:
      return name;
  }
}

function optionLabel(option: string, t: (key: string) => string): string {
  switch (option) {
    case "none":
      return t("none");
    case "low":
      return t("parameter_option_low");
    case "medium":
      return t("parameter_option_medium");
    case "high":
      return t("parameter_option_high");
    default:
      return option;
  }
}

/** Compact capability/context/price chips for the selected model. */
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

/** Segmented "default + options" control for the reasoning-effort kwarg. */
function ReasoningSegmentedControl({
  id,
  value,
  options,
  onChange,
  t
}: {
  id: string;
  value: string | null | undefined;
  options: string[];
  onChange: (value: string | null) => void;
  t: (key: string) => string;
}) {
  const segments: { key: string; value: string | null; label: string }[] = [
    { key: "__default", value: null, label: t("default_behavior") },
    ...options.map((option) => ({ key: option, value: option, label: optionLabel(option, t) }))
  ];
  const active = value ?? null;

  return (
    <div
      id={id}
      role="group"
      aria-label={t("reasoning_effort")}
      className="inline-flex overflow-hidden rounded-md border"
    >
      {segments.map((segment) => {
        const selected = active === segment.value;
        return (
          <button
            key={segment.key}
            type="button"
            aria-pressed={selected}
            onClick={() => onChange(segment.value)}
            className={cn(
              "border-l px-3 py-1.5 text-sm transition-colors first:border-l-0",
              selected
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-muted"
            )}
          >
            {segment.label}
          </button>
        );
      })}
    </div>
  );
}

export function AiSection({ assistant }: { assistant: Assistant }) {
  const t = useTranslations();
  const { space } = useSpace();
  const { tenant } = useAppContext();
  const update = useUpdateAssistant(assistant.id);
  const autosave = useAutosave("ai");

  const savedModelId = assistant.completion_model?.id ?? "";
  const savedKwargs = useMemo<ModelKwargs>(
    () => assistant.completion_model_kwargs ?? {},
    [assistant.completion_model_kwargs]
  );
  const [modelId, setModelId] = useState(savedModelId);
  const [kwargs, setKwargs] = useState<ModelKwargs>(savedKwargs);

  const model = space.completion_models.find((candidate) => candidate.id === modelId) ?? null;
  const behaviour = behaviourFromKwargs(kwargs);
  const presetsSupported = model === null || supportsBehaviorPresets(model);
  const specificKwargs = modelSpecificKwargs(model);
  const showModelPricing = tenant.show_model_pricing === true;

  // Adopt server changes (our own save landing, or an edit elsewhere) unless the
  // user has diverged locally.
  const savedKey = JSON.stringify([savedModelId, savedKwargs]);
  const savedRef = useRef(savedKey);
  useEffect(() => {
    if (savedRef.current === savedKey) return;
    const previous = savedRef.current;
    savedRef.current = savedKey;
    if (JSON.stringify([modelId, kwargs]) === previous) {
      setModelId(savedModelId);
      setKwargs(savedKwargs);
    }
  }, [savedKey, savedModelId, savedKwargs, modelId, kwargs]);

  // Model + kwargs persist together. Selecting a model or a discrete option
  // saves immediately; free-text numbers save on blur.
  const persist = useCallback(
    (nextModelId: string, nextKwargs: ModelKwargs) => {
      const targetModel =
        space.completion_models.find((candidate) => candidate.id === nextModelId) ?? null;
      return autosave(() =>
        update.mutateAsync({
          completion_model: nextModelId ? { id: nextModelId } : null,
          completion_model_kwargs: filterSupportedKwargs(nextKwargs, targetModel)
        })
      );
    },
    [autosave, space.completion_models, update]
  );

  function changeModel(nextModelId: string) {
    setModelId(nextModelId);
    void persist(nextModelId, kwargs);
  }

  function changeKwargs(next: ModelKwargs, save = true) {
    setKwargs(next);
    if (save) void persist(modelId, next);
  }

  function selectBehaviour(next: ModelBehaviour) {
    const preset = kwargsForBehaviour(next);
    if (preset) {
      changeKwargs({ ...kwargs, temperature: preset.temperature });
    } else if (behaviourFromKwargs(kwargs) !== "custom") {
      changeKwargs({ ...kwargs, temperature: 1 });
    }
  }

  const temperatureCap = kwargCapability(model, "temperature");

  return (
    <SettingsGroup title={t("ai_settings")}>
      <SettingsRow
        title={t("completion_model")}
        description={t("this_model_will_be_used")}
        htmlFor="assistant-completion-model"
      >
        <ModelSelector
          id="assistant-completion-model"
          models={space.completion_models}
          selectedId={modelId}
          onSelect={changeModel}
          className="w-full justify-between"
          showPricing={showModelPricing}
        />
        {model && <ModelSummary model={model} showPricing={showModelPricing} t={t} />}
      </SettingsRow>

      {presetsSupported && (
        <SettingsRow
          title={t("model_behaviour")}
          description={t("select_preset_behavior")}
          htmlFor="assistant-model-behaviour"
        >
          <div className="flex flex-col gap-3">
            <Select
              value={behaviour}
              disabled={!model}
              onValueChange={(value) => selectBehaviour(value as ModelBehaviour)}
            >
              <SelectTrigger id="assistant-model-behaviour" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {BEHAVIOUR_LIST.map((candidate) => (
                  <SelectItem key={candidate} value={candidate}>
                    {candidate === "creative"
                      ? t("creative")
                      : candidate === "default"
                        ? t("default_behavior")
                        : candidate === "deterministic"
                          ? t("deterministic")
                          : t("custom")}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {behaviour === "custom" && (
              <div className="flex items-center gap-2">
                <Label htmlFor="custom-temperature" className="text-muted-foreground">
                  {t("temperature")}
                </Label>
                <Input
                  id="custom-temperature"
                  type="number"
                  className="w-28"
                  min={temperatureCap?.minimum ?? 0}
                  max={temperatureCap?.maximum ?? 2}
                  step={temperatureCap?.step ?? 0.05}
                  value={kwargs.temperature ?? 1}
                  onChange={(event) =>
                    changeKwargs({ ...kwargs, temperature: Number(event.target.value) }, false)
                  }
                  onBlur={() => void persist(modelId, kwargs)}
                />
              </div>
            )}
          </div>
        </SettingsRow>
      )}

      {specificKwargs.length > 0 && (
        <SettingsRow title={t("model_settings")} description={t("model_settings_description")}>
          <div className="flex flex-col gap-3">
            {specificKwargs.map((name) => {
              const capability = kwargCapability(model, name);

              if (name === "reasoning_effort") {
                return (
                  <div key={name} className="flex flex-col gap-1.5">
                    <Label htmlFor={`kwarg-${name}`} className="text-muted-foreground font-normal">
                      {kwargLabel(name, t)}
                    </Label>
                    <ReasoningSegmentedControl
                      id={`kwarg-${name}`}
                      value={kwargs[name] as string | null | undefined}
                      options={capability?.options ?? []}
                      onChange={(value) => changeKwargs({ ...kwargs, [name]: value })}
                      t={t}
                    />
                    <p className="text-muted-foreground text-sm">{t("reasoning_effort_help")}</p>
                  </div>
                );
              }

              return (
                <div key={name} className="flex items-center justify-between gap-4">
                  <Label htmlFor={`kwarg-${name}`} className="text-muted-foreground font-normal">
                    {kwargLabel(name, t)}
                  </Label>
                  {isSelectKwarg(name) ? (
                    <Select
                      value={(kwargs[name] as string | null | undefined) ?? "__default"}
                      onValueChange={(value) =>
                        changeKwargs({ ...kwargs, [name]: value === "__default" ? null : value })
                      }
                    >
                      <SelectTrigger id={`kwarg-${name}`} className="w-44">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="__default">{t("default_behavior")}</SelectItem>
                        {(capability?.options ?? []).map((option) => (
                          <SelectItem key={option} value={option}>
                            {optionLabel(option, t)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    <Input
                      id={`kwarg-${name}`}
                      type="number"
                      className="w-28"
                      min={capability?.minimum ?? 0}
                      max={capability?.maximum ?? NUMERIC_DEFAULT_MAX[name] ?? 1}
                      step={capability?.step ?? 0.05}
                      value={(kwargs[name] as number | null | undefined) ?? ""}
                      placeholder="—"
                      onChange={(event) =>
                        changeKwargs(
                          {
                            ...kwargs,
                            [name]: event.target.value === "" ? null : Number(event.target.value)
                          },
                          false
                        )
                      }
                      onBlur={() => void persist(modelId, kwargs)}
                    />
                  )}
                </div>
              );
            })}
          </div>
        </SettingsRow>
      )}
    </SettingsGroup>
  );
}
