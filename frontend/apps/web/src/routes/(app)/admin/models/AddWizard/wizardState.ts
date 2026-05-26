/*
 * Copyright (c) 2026 Sundsvalls Kommun
 *
 * Wizard data shape and a small factory for building the empty initial state.
 * Lives outside the Svelte component so step children can type their props
 * against the same source of truth without triggering a Svelte recompile.
 */
import type { SecurityClassification } from "@intric/intric-js";

export type WizardStepId = "provider" | "credentials" | "models";

export interface WizardModelDraft {
  name: string;
  displayName: string;
  maxInputTokens?: number;
  maxOutputTokens?: number;
  vision?: boolean;
  reasoning?: boolean;
  supportsToolCalling?: boolean;
  family?: string;
  dimensions?: number;
  maxInput?: number;
  hosting?: string;
  description?: string | null;
  /** USD per token. Used by completion + embedding models. */
  inputCostPerToken?: number | null;
  outputCostPerToken?: number | null;
  /** USD per minute of audio. Used by transcription models. */
  costPerMinute?: number | null;
  securityClassification?: SecurityClassification | null;
}

export interface WizardData {
  selectedProviderId: string | null;
  isCreatingNewProvider: boolean;
  selectedProviderType: string;
  models: WizardModelDraft[];
}

export function createEmptyWizardData(): WizardData {
  return {
    selectedProviderId: null,
    isCreatingNewProvider: false,
    selectedProviderType: "openai",
    models: []
  };
}
