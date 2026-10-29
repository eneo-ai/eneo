"use client";

import { useTranslations } from "use-intl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ModelSelector } from "@/components/ai-elements/model-selector";
import { useAppContext } from "@/components/providers/app-context";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAutosave } from "@/components/composites/use-autosave";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { useSpace } from "@/features/spaces/use-space";
import { filterSupportedKwargs, type ModelKwargs } from "@/features/assistants/editor/model-kwargs";
import { ModelKwargsRows } from "@/features/assistants/editor/model-kwargs-rows";
import type { App, InputFieldType } from "../apps";
import { useUpdateApp } from "./use-app";

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

      <ModelKwargsRows
        idPrefix="app"
        model={model}
        kwargs={kwargs}
        behaviourDescription={t("select_preset_behavior")}
        onChange={changeKwargs}
        onCommit={() => void persist(modelId, kwargs, transcriptionId)}
      />
    </SettingsGroup>
  );
}
