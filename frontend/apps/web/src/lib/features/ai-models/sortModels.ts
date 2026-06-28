import type { CompletionModel, EmbeddingModel, TranscriptionModel } from "@eneo/eneo-js";

type Model = (CompletionModel | EmbeddingModel | TranscriptionModel) & { nickname?: string | null };

function sortModel(a: Model, b: Model) {
  if (a.org === b.org) {
    return (a.nickname ?? "a") > (b.nickname ?? "b") ? 1 : -1;
  }
  return (a.org ?? "a") > (b.org ?? "b") ? 1 : -1;
}

/** Will sort an array of `CompletionModel`or `EmbeddingModel`. ATTENTION: sorts in place! */
export function sortModels<T extends Model>(models: T[]): T[] {
  models.sort(sortModel);
  return models;
}
