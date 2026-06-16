"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { ModelSelector } from "@/components/ai-elements/model-selector";
import { useAppContext } from "@/components/providers/app-context";
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
import { SaveRow } from "@/features/assistants/editor/general-section";
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
} from "@/features/assistants/editor/model-kwargs";
import type { App, InputFieldType } from "../apps";
import { useUpdateApp } from "./use-app";

const NUMERIC_DEFAULT_MAX: Partial<Record<ModelKwargName, number>> = {
  top_p: 1,
  presence_penalty: 2,
  frequency_penalty: 2,
  top_k: 100
};

const AUDIO_INPUT_TYPES: InputFieldType[] = ["audio-recorder", "audio-upload"];

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

export function AiSection({ app }: { app: App }) {
  const t = useTranslations();
  const { space } = useSpace();
  const { tenant } = useAppContext();
  const update = useUpdateApp(app.id);

  const usesAudio = app.input_fields.some((field) => AUDIO_INPUT_TYPES.includes(field.type));

  const savedModelId = app.completion_model?.id ?? "";
  const savedKwargs = app.completion_model_kwargs ?? {};
  const savedTranscriptionId = app.transcription_model?.id ?? "";

  const [modelId, setModelId] = useState(savedModelId);
  const [kwargs, setKwargs] = useState<ModelKwargs>(savedKwargs);
  const [transcriptionId, setTranscriptionId] = useState(savedTranscriptionId);

  const model = space.completion_models.find((candidate) => candidate.id === modelId) ?? null;
  const behaviour = behaviourFromKwargs(kwargs);
  const presetsSupported = model === null || supportsBehaviorPresets(model);
  const specificKwargs = modelSpecificKwargs(model);
  const temperatureCap = kwargCapability(model, "temperature");

  const dirty =
    modelId !== savedModelId ||
    JSON.stringify(kwargs) !== JSON.stringify(savedKwargs) ||
    transcriptionId !== savedTranscriptionId;

  function selectBehaviour(next: ModelBehaviour) {
    const preset = kwargsForBehaviour(next);
    if (preset) {
      setKwargs((current) => ({ ...current, temperature: preset.temperature }));
    } else if (behaviourFromKwargs(kwargs) !== "custom") {
      setKwargs((current) => ({ ...current, temperature: 1 }));
    }
  }

  return (
    <SettingsGroup title={t("ai_settings")}>
      {usesAudio && (
        <SettingsRow
          title={t("transcription_model")}
          description={t("transcription_model_description")}
        >
          <Select value={transcriptionId} onValueChange={setTranscriptionId}>
            <SelectTrigger className="w-full">
              <SelectValue placeholder={t("select_a_model")} />
            </SelectTrigger>
            <SelectContent>
              {space.transcription_models.map((candidate) => (
                <SelectItem key={candidate.id} value={candidate.id}>
                  {candidate.nickname ?? candidate.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </SettingsRow>
      )}

      <SettingsRow title={t("completion_model")} description={t("this_model_will_be_used")}>
        <ModelSelector
          models={space.completion_models}
          selectedId={modelId}
          onSelect={setModelId}
          className="w-full justify-between"
          showPricing={tenant.show_model_pricing}
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
                <Label htmlFor="app-custom-temperature" className="text-muted-foreground">
                  {t("temperature")}
                </Label>
                <Input
                  id="app-custom-temperature"
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

      <SaveRow
        dirty={dirty}
        pending={update.isPending}
        onSave={() =>
          update.mutate({
            completion_model: modelId ? { id: modelId } : null,
            completion_model_kwargs: filterSupportedKwargs(kwargs, model),
            transcription_model: transcriptionId ? { id: transcriptionId } : null
          })
        }
        onRevert={() => {
          setModelId(savedModelId);
          setKwargs(savedKwargs);
          setTranscriptionId(savedTranscriptionId);
        }}
      />
    </SettingsGroup>
  );
}
