"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ModelSelector } from "@/components/ai-elements/model-selector";
import { useAppContext } from "@/components/providers/app-context";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAutosave } from "@/components/composites/use-autosave";
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
  modelKwargLabel,
  modelKwargOptionLabel,
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

export function AiSection({ app }: { app: App }) {
  const t = useTranslations();
  const { space } = useSpace();
  const { tenant } = useAppContext();
  const update = useUpdateApp(app.id);
  const autosave = useAutosave("ai");

  const usesAudio = app.input_fields.some((field) => AUDIO_INPUT_TYPES.includes(field.type));

  const savedModelId = app.completion_model?.id ?? "";
  const savedKwargs = useMemo<ModelKwargs>(
    () => app.completion_model_kwargs ?? {},
    [app.completion_model_kwargs]
  );
  const savedTranscriptionId = app.transcription_model?.id ?? "";

  const [modelId, setModelId] = useState(savedModelId);
  const [kwargs, setKwargs] = useState<ModelKwargs>(savedKwargs);
  const [transcriptionId, setTranscriptionId] = useState(savedTranscriptionId);

  const model = space.completion_models.find((candidate) => candidate.id === modelId) ?? null;
  const behaviour = behaviourFromKwargs(kwargs);
  const presetsSupported = model === null || supportsBehaviorPresets(model);
  const specificKwargs = modelSpecificKwargs(model);
  const temperatureCap = kwargCapability(model, "temperature");

  // Adopt server changes (our own save landing) unless the user diverged.
  const savedKey = JSON.stringify([savedModelId, savedKwargs, savedTranscriptionId]);
  const savedRef = useRef(savedKey);
  useEffect(() => {
    if (savedRef.current === savedKey) return;
    const previous = savedRef.current;
    savedRef.current = savedKey;
    if (JSON.stringify([modelId, kwargs, transcriptionId]) === previous) {
      setModelId(savedModelId);
      setKwargs(savedKwargs);
      setTranscriptionId(savedTranscriptionId);
    }
  }, [savedKey, savedModelId, savedKwargs, savedTranscriptionId, modelId, kwargs, transcriptionId]);

  // Completion model + kwargs + transcription model persist together; discrete
  // choices save immediately, free-text numbers on blur.
  const persist = useCallback(
    (nextModelId: string, nextKwargs: ModelKwargs, nextTranscriptionId: string) => {
      const targetModel =
        space.completion_models.find((candidate) => candidate.id === nextModelId) ?? null;
      return autosave(() =>
        update.mutateAsync({
          completion_model: nextModelId ? { id: nextModelId } : null,
          completion_model_kwargs: filterSupportedKwargs(nextKwargs, targetModel),
          transcription_model: nextTranscriptionId ? { id: nextTranscriptionId } : null
        })
      );
    },
    [autosave, space.completion_models, update]
  );

  function changeModel(nextModelId: string) {
    setModelId(nextModelId);
    void persist(nextModelId, kwargs, transcriptionId);
  }

  function changeTranscription(nextTranscriptionId: string) {
    setTranscriptionId(nextTranscriptionId);
    void persist(modelId, kwargs, nextTranscriptionId);
  }

  function changeKwargs(next: ModelKwargs, save = true) {
    setKwargs(next);
    if (save) void persist(modelId, next, transcriptionId);
  }

  function selectBehaviour(next: ModelBehaviour) {
    const preset = kwargsForBehaviour(next);
    if (preset) {
      changeKwargs({ ...kwargs, temperature: preset.temperature });
    } else if (behaviourFromKwargs(kwargs) !== "custom") {
      changeKwargs({ ...kwargs, temperature: 1 });
    }
  }

  return (
    <SettingsGroup title={t("ai_settings")}>
      {usesAudio && (
        <SettingsRow
          title={t("transcription_model")}
          description={t("transcription_model_description")}
          htmlFor="app-transcription-model"
        >
          <Select value={transcriptionId} onValueChange={changeTranscription}>
            <SelectTrigger id="app-transcription-model" className="w-full">
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

      <SettingsRow
        title={t("completion_model")}
        description={t("this_model_will_be_used")}
        htmlFor="app-completion-model"
      >
        <ModelSelector
          id="app-completion-model"
          models={space.completion_models}
          selectedId={modelId}
          onSelect={changeModel}
          className="w-full justify-between"
          showPricing={tenant.show_model_pricing}
        />
      </SettingsRow>

      {presetsSupported && (
        <SettingsRow
          title={t("model_behaviour")}
          description={t("select_preset_behavior")}
          htmlFor="app-model-behaviour"
        >
          <div className="flex flex-col gap-3">
            <Select
              value={behaviour}
              disabled={!model}
              onValueChange={(value) => selectBehaviour(value as ModelBehaviour)}
            >
              <SelectTrigger id="app-model-behaviour" className="w-full">
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
                    changeKwargs({ ...kwargs, temperature: Number(event.target.value) }, false)
                  }
                  onBlur={() => void persist(modelId, kwargs, transcriptionId)}
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
                  <Label
                    htmlFor={`app-kwarg-${name}`}
                    className="text-muted-foreground font-normal"
                  >
                    {modelKwargLabel(name, t)}
                  </Label>
                  {isSelectKwarg(name) ? (
                    <Select
                      value={(kwargs[name] as string | null | undefined) ?? "__default"}
                      onValueChange={(value) =>
                        changeKwargs({ ...kwargs, [name]: value === "__default" ? null : value })
                      }
                    >
                      <SelectTrigger id={`app-kwarg-${name}`} className="w-44">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="__default">{t("default_behavior")}</SelectItem>
                        {(capability?.options ?? []).map((option) => (
                          <SelectItem key={option} value={option}>
                            {modelKwargOptionLabel(option, t)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    <Input
                      id={`app-kwarg-${name}`}
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
                      onBlur={() => void persist(modelId, kwargs, transcriptionId)}
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
