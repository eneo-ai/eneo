"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Binding } from "@/features/skills/skill-bindings";
import { type Capability } from "@/features/capabilities/capabilities";
import { GOVERNANCE_POLICY_KEY, type GovernancePolicy } from "./governance";
import {
  activeProviders,
  buildConfirmations,
  buildUpdate,
  canSave as canSaveOf,
  type CompletionModel,
  type ConfirmKey,
  defaultModelId as defaultModelIdOf,
  defaultValid as defaultValidOf,
  displayServers,
  draftReducer,
  effectiveModelIdSet,
  fileDirty,
  mcpDirty,
  mcpValid as mcpValidOf,
  type McpServer,
  type ModelProviderLite,
  modelsByProvider as modelsByProviderOf,
  modelsDirty,
  type PromptOption,
  promptDirty,
  policyServers,
  capabilityMarker,
  reasoningDirty,
  reasoningOptions as reasoningOptionsOf,
  seedEditable,
  selectableModels,
  selectableServerIdSet,
  selectableToolIdSet,
  skillsDirty,
  skillsValid as skillsValidOf
} from "./policy-draft";

export type BadgeVariant = "default" | "outline" | "destructive";

export type PolicyDraftInput = {
  policy: GovernancePolicy;
  models: CompletionModel[];
  providers: ModelProviderLite[];
  servers: McpServer[];
  prompts: PromptOption[];
  selectiveActivationEnabled: boolean;
};

const badgeVariant = (enabled: boolean, valid: boolean): BadgeVariant =>
  enabled ? (valid ? "default" : "destructive") : "outline";

/**
 * Editable governance-policy draft for the personal assistant: wires the pure
 * reducer/selectors in `policy-draft` to React state, derives the translated
 * summaries, tracks dirtiness against the saved baseline, and owns the
 * confirm-before-apply save flow.
 */
export function usePolicyDraft(input: PolicyDraftInput) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const { policy, prompts } = input;

  // Prepared source lists (only what the policy can legally reference).
  const models = useMemo(() => selectableModels(input.models), [input.models]);
  const providers = useMemo(() => activeProviders(input.providers), [input.providers]);
  const available = useMemo(() => policyServers(input.servers), [input.servers]);
  const display = useMemo(() => displayServers(available), [available]);
  const serverIds = useMemo(() => selectableServerIdSet(available), [available]);
  const toolIds = useMemo(() => selectableToolIdSet(available), [available]);

  const seed = useMemo(() => seedEditable(policy, models, available), [policy, models, available]);
  const [state, dispatch] = useReducer(draftReducer, seed);

  // Re-seed to the new baseline whenever the policy reference changes (mount and
  // after a save + invalidate). Reading the saved policy only — no read-after-write.
  const seededFor = useRef(policy);
  useEffect(() => {
    if (seededFor.current !== policy) {
      seededFor.current = policy;
      dispatch({ type: "reseed", state: seed });
    }
  }, [policy, seed]);

  // ---- Derived -------------------------------------------------------------
  const byProvider = useMemo(() => modelsByProviderOf(models), [models]);
  const effectiveModelIds = useMemo(
    () => effectiveModelIdSet(state, byProvider),
    [state, byProvider]
  );
  const defaultModelId = useMemo(() => defaultModelIdOf(state), [state]);
  const providerSelections = useMemo(() => new Set(state.providerSelections), [state]);
  const disabledMcpToolIds = useMemo(() => new Set(state.disabledMcpToolIds), [state]);
  const reasoningOptions = useMemo(
    () => reasoningOptionsOf(models, state, effectiveModelIds),
    [models, state, effectiveModelIds]
  );

  const mDirty = useMemo(() => modelsDirty(state, policy), [state, policy]);
  const cDirty = useMemo(
    () => mcpDirty(state, policy, serverIds, toolIds),
    [state, policy, serverIds, toolIds]
  );
  const pDirty = useMemo(() => promptDirty(state, policy), [state, policy]);
  const rDirty = useMemo(() => reasoningDirty(state, policy), [state, policy]);
  const fDirty = useMemo(() => fileDirty(state, policy), [state, policy]);
  const sDirty = useMemo(() => skillsDirty(state, policy), [state, policy]);
  const dirty = mDirty || cDirty || pDirty || rDirty || fDirty || sDirty;

  const defaultValid = defaultValidOf(state, effectiveModelIds);
  const mcpValid = mcpValidOf(state);
  const skillsValid = skillsValidOf(state, input.selectiveActivationEnabled);
  const reasoningValid =
    state.defaultReasoningEffort === null ||
    reasoningOptions.includes(state.defaultReasoningEffort);
  const canSave = canSaveOf(
    state,
    dirty,
    effectiveModelIds,
    input.selectiveActivationEnabled,
    reasoningOptions
  );

  // ---- Summaries -----------------------------------------------------------
  const modelsSummary = useMemo(() => {
    if (!state.modelsEnabled) return t("governance_models_summary_inactive");
    const total = effectiveModelIds.size;
    if (total === 0) return t("governance_models_summary_none");
    if (total === 1) return t("governance_models_summary_single");
    const providerCount = state.providerSelections.length;
    if (providerCount === 0) return t("governance_models_summary_count", { count: total });
    return providerCount === 1
      ? t("governance_models_summary_count_provider_one", {
          count: total,
          providers: providerCount
        })
      : t("governance_models_summary_count_provider_other", {
          count: total,
          providers: providerCount
        });
  }, [state.modelsEnabled, state.providerSelections, effectiveModelIds, t]);

  const mcpSummary = useMemo(() => {
    if (!state.mcpEnabled) return t("governance_mcp_summary_inactive");
    const selected = Object.keys(state.mcpSelections).length;
    if (selected === 0) return t("governance_mcp_summary_none");
    return t("governance_mcp_summary_count", { selected, total: available.length });
  }, [state.mcpEnabled, state.mcpSelections, available.length, t]);

  const promptSummary = useMemo(() => {
    if (!state.promptEnabled) return t("governance_prompt_summary_inactive");
    if (!state.selectedPromptId) return t("governance_prompt_summary_none");
    const name =
      prompts.find((prompt) => prompt.id === state.selectedPromptId)?.name ??
      t("governance_prompt_unknown");
    return t("governance_prompt_summary_selected", { name });
  }, [state.promptEnabled, state.selectedPromptId, prompts, t]);
  const skillsSummary =
    state.skillBindings.length === 0
      ? t("governance_skills_summary_none")
      : t("governance_skills_summary_count", { count: String(state.skillBindings.length) });
  const reasoningSummary = !state.reasoningConfigured
    ? t("governance_reasoning_summary_inactive")
    : t(
        state.allowUserReasoningEffort
          ? "governance_reasoning_summary_user_choice"
          : "governance_reasoning_summary_fixed",
        { effort: state.defaultReasoningEffort ?? t("default_behavior") }
      );
  const filesSummary = !(policy.file_policy.configured || fDirty)
    ? t("governance_files_summary_inactive")
    : state.openFilesEnabled
      ? t("governance_files_summary_open_files")
      : t("governance_files_summary_inline");

  const providerName = (pid: string | null): string =>
    pid === null
      ? t("governance_provider_other_models")
      : (providers.find((provider) => provider.id === pid)?.name ??
        t("governance_provider_unknown"));

  // ---- Save lifecycle ------------------------------------------------------
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveAnnouncement, setSaveAnnouncement] = useState("");
  const [pendingConfirm, setPendingConfirm] = useState<ConfirmKey[] | null>(null);

  const doSave = async () => {
    setSaving(true);
    setSaveError(null);
    setSaveAnnouncement("");
    try {
      const update = buildUpdate(
        state,
        {
          models: mDirty,
          mcp: cDirty,
          prompt: pDirty,
          reasoning: rDirty,
          file: fDirty,
          skills: sDirty
        },
        available
      );
      await unwrap(browserApi.PUT("/api/v1/admin/governance-policy/", { body: update }));
      await queryClient.invalidateQueries({ queryKey: GOVERNANCE_POLICY_KEY });
      setPendingConfirm(null);
      setSaveAnnouncement(t("governance_save_success"));
    } catch (error) {
      setSaveError((error as { message?: string }).message ?? t("governance_save_error"));
      setSaveAnnouncement(t("governance_save_failure"));
    } finally {
      setSaving(false);
    }
  };

  const save = () => {
    const confirmations = buildConfirmations(state, policy, effectiveModelIds.size);
    if (confirmations.length > 0) setPendingConfirm(confirmations);
    else void doSave();
  };

  return {
    // models section
    modelsEnabled: state.modelsEnabled,
    setModelsEnabled: (on: boolean) => dispatch({ type: "setModelsEnabled", on }),
    modelsByProvider: byProvider,
    modelSelections: state.modelSelections,
    providerSelections,
    effectiveModelIds,
    defaultModelId,
    modelsSummary,
    defaultValid,
    toggleModelSelected: (id: string, on: boolean) => dispatch({ type: "toggleModel", id, on }),
    setSingleDefault: (id: string) => dispatch({ type: "setDefault", id }),
    toggleProvider: (pid: string, on: boolean) =>
      dispatch({
        type: "toggleProvider",
        pid,
        on,
        providerModelIds: (byProvider.get(pid) ?? []).map((model) => model.id)
      }),
    // mcp section
    mcpEnabled: state.mcpEnabled,
    setMcpEnabled: (on: boolean) => dispatch({ type: "setMcpEnabled", on }),
    allMcpServers: display,
    mcpSelections: state.mcpSelections,
    disabledMcpToolIds,
    mcpSummary,
    mcpValid,
    toggleMcp: (id: string, on: boolean) =>
      dispatch({
        type: "toggleMcp",
        id,
        on,
        toolIds: (available.find((server) => server.id === id)?.tools ?? []).map((tool) => tool.id)
      }),
    toggleMcpDefault: (id: string, on: boolean) => dispatch({ type: "toggleMcpDefault", id, on }),
    toggleMcpTool: (toolId: string, on: boolean) => dispatch({ type: "toggleMcpTool", toolId, on }),
    toggleCapability: (purpose: Capability, on: boolean) => {
      const id = capabilityMarker(purpose);
      if (on && !available.find((server) => server.id === id)?.is_available) return;
      dispatch({ type: "toggleMcp", id, on, toolIds: [] });
    },
    toggleCapabilityDefault: (purpose: Capability, on: boolean) =>
      dispatch({ type: "toggleMcpDefault", id: capabilityMarker(purpose), on }),
    // prompt section
    promptEnabled: state.promptEnabled,
    setPromptEnabled: (on: boolean) => dispatch({ type: "setPromptEnabled", on }),
    selectedPromptId: state.selectedPromptId,
    setSelectedPromptId: (id: string | null) => dispatch({ type: "setPrompt", id }),
    promptOptions: prompts,
    promptSummary,
    // reasoning and attachment policy
    reasoningConfigured: state.reasoningConfigured,
    activateReasoning: () => dispatch({ type: "activateReasoning" }),
    defaultReasoningEffort: state.defaultReasoningEffort,
    setReasoningEffort: (effort: string | null) => dispatch({ type: "setReasoningEffort", effort }),
    allowUserReasoningEffort: state.allowUserReasoningEffort,
    setReasoningOverride: (on: boolean) => dispatch({ type: "setReasoningOverride", on }),
    reasoningOptions,
    reasoningSummary,
    reasoningValid,
    openFilesEnabled: state.openFilesEnabled,
    setOpenFiles: (on: boolean) => dispatch({ type: "setOpenFiles", on }),
    filesSummary,
    // personal-chat Skills
    skillBindings: state.skillBindings,
    setSkillBindings: (bindings: Binding[]) => dispatch({ type: "setSkillBindings", bindings }),
    skillsSummary,
    skillsValid,
    // shared
    badgeVariant,
    providerName,
    // save lifecycle
    dirty,
    canSave,
    saving,
    saveError,
    saveAnnouncement,
    pendingConfirm,
    save,
    confirmSave: () => void doSave(),
    cancelConfirm: () => setPendingConfirm(null),
    discard: () => dispatch({ type: "reseed", state: seed })
  };
}

export type PolicyDraft = ReturnType<typeof usePolicyDraft>;
