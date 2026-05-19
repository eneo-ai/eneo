/*
 * Copyright (c) 2026 Sundsvalls Kommun
 *
 * In-progress model state used by both the AddWizard (Step 3) and the
 * EditModelDialog. Number-typed fields are kept as strings while the user
 * is typing to avoid the usual "0/NaN/empty" race; they are converted on
 * submit.
 */
import type {
  CompletionModel,
  EmbeddingModel,
  SecurityClassification,
  TranscriptionModel
} from "@intric/intric-js";
import type { WizardModelDraft } from "../wizardState";
import { PROVIDER_DEFAULT_HOSTING } from "../../modelProviderCapabilities";

export type ModelType = "completion" | "embedding" | "transcription";

export interface ModelDraftState {
  name: string;
  displayName: string;
  maxInputTokensStr: string;
  maxOutputTokensStr: string;
  vision: boolean;
  reasoning: boolean;
  supportsToolCalling: boolean;
  family: string;
  dimensionsStr: string;
  maxInputStr: string;
  hosting: string;
  description: string;
  /** USD per token. Stored as a string while the user types so empty input is
   *  unambiguous (vs. NaN/0). Converted on submit. */
  inputCostPerTokenStr: string;
  outputCostPerTokenStr: string;
  /** USD per minute of audio (transcription only). */
  costPerMinuteStr: string;
  securityClassification: SecurityClassification | null;
}

export function createEmptyDraft(modelType: ModelType, providerType: string): ModelDraftState {
  return {
    name: "",
    displayName: "",
    maxInputTokensStr: "",
    maxOutputTokensStr: "",
    vision: false,
    reasoning: false,
    supportsToolCalling: false,
    family: modelType === "embedding" ? "openai" : providerType || "openai",
    dimensionsStr: "",
    maxInputStr: "",
    hosting: PROVIDER_DEFAULT_HOSTING[providerType] ?? "swe",
    description: "",
    inputCostPerTokenStr: "",
    outputCostPerTokenStr: "",
    costPerMinuteStr: "",
    securityClassification: null
  };
}

const TOKENS_PER_MILLION = 1_000_000;

/**
 * Per-token cost columns are `Numeric(20, 12)` (Postgres) — at most 8 integer
 * digits, i.e. strictly less than 10^8 USD per token. Translated into the
 * per-1M-tokens admins type, that's < 10^14. Per-minute cost is `Numeric(20, 6)`
 * which independently allows < 10^14 USD per minute. We use a single shared
 * cap for all three fields so the form can validate before the DB rejects.
 *
 * Mirror change: `backend/src/intric/database/tables/ai_models_table.py` —
 * keep the `Numeric(...)` precisions and this constant in sync.
 */
export const MAX_COST_INPUT = 99_999_999_999_999;
const MAX_TOKEN_COST_PER_TOKEN = MAX_COST_INPUT / TOKENS_PER_MILLION;

/** Coerce a `<Input type="number" bind:value>` field to a finite number,
 *  returning null for empty/blank/non-numeric input. */
export function rawCostToNumber(value: string | number | null | undefined): number | null {
  if (value == null) return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : null;
}

/** Returns the first cost field whose entered value exceeds the DB cap, or
 *  null when all are safe. Compares against the per-1M / per-minute value
 *  the admin typed — same units as `MAX_COST_INPUT`, no conversion. */
export function findDraftCostOverflow(
  draft: ModelDraftState
): "input" | "output" | "perMinute" | null {
  const candidates: Array<["input" | "output" | "perMinute", string | number]> = [
    ["input", draft.inputCostPerTokenStr],
    ["output", draft.outputCostPerTokenStr],
    ["perMinute", draft.costPerMinuteStr]
  ];
  for (const [key, raw] of candidates) {
    const n = rawCostToNumber(raw);
    if (n != null && Math.abs(n) > MAX_COST_INPUT) return key;
  }
  return null;
}

/** Same overflow check as `findDraftCostOverflow`, but for already-converted
 *  WizardModelDraft values (token cost stored per-token). The per-token DB
 *  cap is `MAX_COST_INPUT / TOKENS_PER_MILLION`; the per-minute value
 *  shares the same `MAX_COST_INPUT` budget directly. */
export function isCostValueOverflow(value: number | null | undefined, perMinute = false): boolean {
  if (value == null || !Number.isFinite(value)) return false;
  const cap = perMinute ? MAX_COST_INPUT : MAX_TOKEN_COST_PER_TOKEN;
  return Math.abs(value) > cap;
}

/**
 * Completion models cannot be saved without positive token budgets — the
 * backend rejects 0/null and downstream tokenizer math divides by them.
 * Embedding and transcription drafts have no equivalent constraint.
 */
export function hasValidCompletionTokenBudgets(draft: ModelDraftState): boolean {
  return (
    draft.maxInputTokensStr !== "" &&
    parseInt(draft.maxInputTokensStr, 10) > 0 &&
    draft.maxOutputTokensStr !== "" &&
    parseInt(draft.maxOutputTokensStr, 10) > 0
  );
}

/**
 * "Complete enough to be saved." Mirrors the rules used by the original
 * StepModels.canAddModel — embeddings and transcription only need a name
 * and display name; completion also requires non-zero token budgets.
 */
export function isDraftComplete(draft: ModelDraftState, modelType: ModelType): boolean {
  if (draft.name.trim() === "" || draft.displayName.trim() === "") return false;
  if (modelType !== "completion") return true;
  return hasValidCompletionTokenBudgets(draft);
}

/**
 * Form ↔ API unit boundary for token-priced models.
 *
 * The DB column stores USD per *single* token (matches LiteLLM and what the
 * usage-stats math expects). Admins, however, expect to type "5" for "$5 per
 * 1M tokens" because that is how every provider quotes prices today. These
 * helpers convert between the two representations and live here so all
 * callers (wizard, edit dialog, catalog lookup) stay in agreement.
 */
export function tokenCostFromPerMillion(value: string | number | null | undefined): number | null {
  const n = rawCostToNumber(value);
  return n == null ? null : n / TOKENS_PER_MILLION;
}

export function perMillionFromTokenCost(value: number | string | null | undefined): string {
  if (value == null) return "";
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "";
  // toPrecision(10) trims float-mul noise like 5e-6 * 1e6 = 4.999999999999999.
  return Number((n * TOKENS_PER_MILLION).toPrecision(10)).toString();
}

export function draftToWizardModel(draft: ModelDraftState): WizardModelDraft {
  return {
    name: draft.name,
    displayName: draft.displayName,
    maxInputTokens: draft.maxInputTokensStr ? parseInt(draft.maxInputTokensStr, 10) : undefined,
    maxOutputTokens: draft.maxOutputTokensStr ? parseInt(draft.maxOutputTokensStr, 10) : undefined,
    vision: draft.vision,
    reasoning: draft.reasoning,
    supportsToolCalling: draft.supportsToolCalling,
    family: draft.family,
    dimensions: draft.dimensionsStr ? parseInt(draft.dimensionsStr, 10) : undefined,
    maxInput: draft.maxInputStr ? parseInt(draft.maxInputStr, 10) : undefined,
    hosting: draft.hosting,
    description: draft.description.trim() || null,
    inputCostPerToken: tokenCostFromPerMillion(draft.inputCostPerTokenStr),
    outputCostPerToken: tokenCostFromPerMillion(draft.outputCostPerTokenStr),
    costPerMinute: rawCostToNumber(draft.costPerMinuteStr),
    securityClassification: draft.securityClassification
  };
}

/**
 * Catalog model info shape returned by both the live `/v1/models` endpoint
 * and the static LiteLLM fallback. Kept in this module so all consumers
 * agree on the field names.
 */
export interface ModelInfo {
  name: string;
  display_name?: string;
  mode?: string;
  max_input_tokens?: number;
  max_output_tokens?: number;
  supports_vision?: boolean;
  supports_function_calling?: boolean;
  supports_reasoning?: boolean;
  output_vector_size?: number;
  input_cost_per_token?: number | null;
  output_cost_per_token?: number | null;
  cost_per_minute?: number | null;
}

/** Stringify a USD cost coming from the backend (which may be string or number). */
function costToString(value: number | string | null | undefined): string {
  if (value == null) return "";
  return typeof value === "number" ? String(value) : value;
}

/**
 * Build a draft from an existing model record. Used by EditModelDialog so
 * the same form component can power both create and edit flows.
 */
export function modelToDraft(
  model: CompletionModel | EmbeddingModel | TranscriptionModel,
  modelType: ModelType
): ModelDraftState {
  const base: ModelDraftState = {
    name: model.name,
    displayName: ("nickname" in model && model.nickname) || model.name,
    maxInputTokensStr: "",
    maxOutputTokensStr: "",
    vision: false,
    reasoning: false,
    supportsToolCalling: false,
    family: ("family" in model && model.family) || "openai",
    dimensionsStr: "",
    maxInputStr: "",
    hosting: model.hosting ?? "swe",
    description: model.description ?? "",
    inputCostPerTokenStr: "",
    outputCostPerTokenStr: "",
    costPerMinuteStr: "",
    securityClassification: model.security_classification ?? null
  };

  if (modelType === "completion" && "max_input_tokens" in model) {
    base.maxInputTokensStr = String(model.max_input_tokens ?? "");
    base.maxOutputTokensStr = String(model.max_output_tokens ?? "");
    base.vision = model.vision ?? false;
    base.reasoning = model.reasoning ?? false;
    base.supportsToolCalling = model.supports_tool_calling ?? false;
    base.inputCostPerTokenStr = perMillionFromTokenCost(model.input_cost_per_token);
    base.outputCostPerTokenStr = perMillionFromTokenCost(model.output_cost_per_token);
  } else if (modelType === "embedding" && "dimensions" in model) {
    base.dimensionsStr = model.dimensions != null ? String(model.dimensions) : "";
    base.maxInputStr = model.max_input != null ? String(model.max_input) : "";
    base.inputCostPerTokenStr = perMillionFromTokenCost(model.input_cost_per_token);
    base.outputCostPerTokenStr = perMillionFromTokenCost(model.output_cost_per_token);
  } else if (modelType === "transcription" && "cost_per_minute" in model) {
    base.costPerMinuteStr = costToString(model.cost_per_minute);
  }

  return base;
}

export function applyCatalogModelToDraft(
  draft: ModelDraftState,
  info: ModelInfo,
  modelType: ModelType
): ModelDraftState {
  const next: ModelDraftState = {
    ...draft,
    name: info.name,
    displayName: info.display_name ?? info.name
  };
  if (modelType === "completion") {
    next.maxInputTokensStr = info.max_input_tokens != null ? String(info.max_input_tokens) : "";
    next.maxOutputTokensStr = info.max_output_tokens != null ? String(info.max_output_tokens) : "";
    next.vision = info.supports_vision ?? false;
    next.reasoning = info.supports_reasoning ?? false;
    next.supportsToolCalling = info.supports_function_calling ?? false;
  } else if (modelType === "embedding") {
    next.dimensionsStr = info.output_vector_size != null ? String(info.output_vector_size) : "";
    next.maxInputStr = info.max_input_tokens != null ? String(info.max_input_tokens) : "";
  }
  if (modelType === "transcription") {
    if (info.cost_per_minute != null) next.costPerMinuteStr = String(info.cost_per_minute);
  } else {
    if (info.input_cost_per_token != null) {
      next.inputCostPerTokenStr = perMillionFromTokenCost(info.input_cost_per_token);
    }
    if (info.output_cost_per_token != null) {
      next.outputCostPerTokenStr = perMillionFromTokenCost(info.output_cost_per_token);
    }
  }
  return next;
}
