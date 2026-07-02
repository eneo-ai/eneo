import type { CompletionModel, TranscriptionModel } from "@eneo/eneo-js";

type CompletionModelAvailability = Pick<CompletionModel, "can_access">;
type TranscriptionModelAvailability = Pick<TranscriptionModel, "can_access">;
type SpaceModelAvailability = {
  completion_models: readonly CompletionModelAvailability[];
  transcription_models: readonly TranscriptionModelAvailability[];
};

export function hasAccessibleCompletionModel(
  models: readonly CompletionModelAvailability[] | null | undefined
): boolean {
  return models?.some((model) => model.can_access === true) ?? false;
}

export function hasAccessibleTranscriptionModel(
  models: readonly TranscriptionModelAvailability[] | null | undefined
): boolean {
  return models?.some((model) => model.can_access === true) ?? false;
}

export function spaceCanCreateApps(space: SpaceModelAvailability): boolean {
  return (
    hasAccessibleCompletionModel(space.completion_models) &&
    hasAccessibleTranscriptionModel(space.transcription_models)
  );
}
