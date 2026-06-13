"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { ModelSelector } from "@/components/ai-elements/model-selector";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { useSpace } from "@/features/spaces/use-space";
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
import { SaveRow } from "./general-section";
import { useUpdateAssistant, type Assistant } from "./use-assistant";

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

export function AiSection({ assistant }: { assistant: Assistant }) {
  const t = useTranslations();
  const { space } = useSpace();
  const update = useUpdateAssistant(assistant.id);

  const savedModelId = assistant.completion_model?.id ?? "";
  const savedKwargs = assistant.completion_model_kwargs ?? {};
  const [modelId, setModelId] = useState(savedModelId);
  const [kwargs, setKwargs] = useState<ModelKwargs>(savedKwargs);

  const model = space.completion_models.find((candidate) => candidate.id === modelId) ?? null;
  const behaviour = behaviourFromKwargs(kwargs);
  const presetsSupported = model === null || supportsBehaviorPresets(model);
  const specificKwargs = modelSpecificKwargs(model);

  const dirty = modelId !== savedModelId || JSON.stringify(kwargs) !== JSON.stringify(savedKwargs);

  function selectBehaviour(next: ModelBehaviour) {
    const preset = kwargsForBehaviour(next);
    if (preset) {
      setKwargs((current) => ({ ...current, temperature: preset.temperature }));
    } else if (behaviourFromKwargs(kwargs) !== "custom") {
      setKwargs((current) => ({ ...current, temperature: 1 }));
    }
  }

  const temperatureCap = kwargCapability(model, "temperature");

  const saveRow = (
    <SaveRow
      dirty={dirty}
      pending={update.isPending}
      onSave={() =>
        update.mutate({
          completion_model: modelId ? { id: modelId } : null,
          completion_model_kwargs: filterSupportedKwargs(kwargs, model)
        })
      }
      onRevert={() => {
        setModelId(savedModelId);
        setKwargs(savedKwargs);
      }}
    />
  );

  return (
    <SettingsGroup title={t("ai_settings")}>
      <SettingsRow title={t("completion_model")} description={t("this_model_will_be_used")}>
        <ModelSelector
          models={space.completion_models}
          selectedId={modelId}
          onSelect={setModelId}
          className="w-full justify-between"
        />
      </SettingsRow>

      {presetsSupported && (
        <SettingsRow title={t("model_behaviour")} description={t("select_preset_behavior")}>
          <div className="flex flex-col gap-3">
            <Select
              value={behaviour}
              disabled={!model}
              onValueChange={(value) => selectBehaviour(value as ModelBehaviour)}
            >
              <SelectTrigger className="w-full" aria-label={t("select_model_behaviour")}>
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
                    setKwargs((current) => ({
                      ...current,
                      temperature: Number(event.target.value)
                    }))
                  }
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
              return (
                <div key={name} className="flex items-center justify-between gap-4">
                  <Label className="text-muted-foreground font-normal">{kwargLabel(name, t)}</Label>
                  {isSelectKwarg(name) ? (
                    <Select
                      value={(kwargs[name] as string | null | undefined) ?? "__default"}
                      onValueChange={(value) =>
                        setKwargs((current) => ({
                          ...current,
                          [name]: value === "__default" ? null : value
                        }))
                      }
                    >
                      <SelectTrigger className="w-44">
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
                      type="number"
                      className="w-28"
                      min={capability?.minimum ?? 0}
                      max={capability?.maximum ?? NUMERIC_DEFAULT_MAX[name] ?? 1}
                      step={capability?.step ?? 0.05}
                      value={(kwargs[name] as number | null | undefined) ?? ""}
                      placeholder="—"
                      onChange={(event) =>
                        setKwargs((current) => ({
                          ...current,
                          [name]: event.target.value === "" ? null : Number(event.target.value)
                        }))
                      }
                    />
                  )}
                </div>
              );
            })}
          </div>
        </SettingsRow>
      )}

      {saveRow}
    </SettingsGroup>
  );
}
