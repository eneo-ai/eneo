/*
 * Copyright (c) 2026 Sundsvalls Kommun
 *
 * Build a `model_id -> rate` lookup map from the result of `intric.models.list()`.
 * Used by token-stats tables to apply the *current* ratecard to *historical*
 * token counts. Transcription models intentionally absent — they're priced per
 * minute of audio, not per token, and the token-stats endpoint deals in tokens.
 */
import type { CompletionModel, EmbeddingModel } from "@intric/intric-js";
import type { CostFieldValue } from "./formatModelStats";

export interface CostRate {
  input_cost_per_token: CostFieldValue;
  output_cost_per_token: CostFieldValue;
}

export type CostRateMap = Map<string, CostRate>;

export function buildCostRateMap(modelList: {
  completionModels: CompletionModel[];
  embeddingModels: EmbeddingModel[];
}): CostRateMap {
  const map: CostRateMap = new Map();
  for (const model of modelList.completionModels) {
    map.set(model.id, {
      input_cost_per_token: model.input_cost_per_token ?? null,
      output_cost_per_token: model.output_cost_per_token ?? null
    });
  }
  for (const model of modelList.embeddingModels) {
    map.set(model.id, {
      input_cost_per_token: model.input_cost_per_token ?? null,
      output_cost_per_token: model.output_cost_per_token ?? null
    });
  }
  return map;
}
