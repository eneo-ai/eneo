import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAutosave } from "@/components/composites/use-autosave";
import { useSpace } from "@/features/spaces/use-space";
import { assistantToolModel } from "./effective-config";
import { filterSupportedKwargs, type ModelKwargs } from "./model-kwargs";
import { useUpdateAssistant, type Assistant } from "./use-assistant";

/** Model and parameters remain one draft and one existing assistant save. */
export function useAssistantAiDraft(assistant: Assistant) {
  const { space } = useSpace();
  const update = useUpdateAssistant(assistant.id);
  const autosave = useAutosave("ai");
  const savedModelId = assistant.completion_model?.id ?? "";
  const savedKwargs = useMemo<ModelKwargs>(
    () => assistant.completion_model_kwargs ?? {},
    [assistant.completion_model_kwargs]
  );
  const [modelId, setModelId] = useState(savedModelId);
  const [kwargs, setKwargs] = useState<ModelKwargs>(savedKwargs);
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
  const model = space.completion_models.find((candidate) => candidate.id === modelId) ?? null;
  const toolModel = assistantToolModel(space.completion_models, {
    ...assistant,
    completion_model: model ?? (modelId === savedModelId ? assistant.completion_model : null)
  });
  const effectiveModel =
    space.completion_models.find((candidate) => candidate.id === toolModel?.id) ?? null;
  const confirmed =
    !update.isPending &&
    toolModel?.id === assistantToolModel(space.completion_models, assistant)?.id;
  return {
    modelId,
    kwargs,
    model,
    toolModel,
    effectiveModel,
    confirmed,
    persist,
    changeModel,
    changeKwargs,
    isError: update.isError
  };
}

export type AssistantAiDraft = ReturnType<typeof useAssistantAiDraft>;
