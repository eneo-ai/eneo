/*
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
*/

/**
 * Editable draft of the governance policy for the personal assistant.
 *
 * Owns all of the configuration page's interactive state: the per-dimension
 * selections, dirty tracking against the last-saved baseline, validation,
 * human-readable summaries, the confirm-before-apply flow and the save call.
 * The `+page.svelte` is left as thin wiring that binds sections to this draft.
 *
 * Reactivity contract: `sync()` reads only from its `data` argument (never
 * from the draft's own `$state`), so the page can call it from an `$effect`
 * keyed on `data` — after a save + `invalidate()` the form re-seeds to the new
 * baseline without a read-after-write cycle.
 */

import { invalidate } from "$app/navigation";
import { m } from "$lib/paraglide/messages";
import { SvelteMap, SvelteSet } from "svelte/reactivity";
import type { Intric } from "@intric/intric-js";

type ModelSelection = { selected: boolean; isDefault: boolean };
type CompletionModel = {
  id: string;
  provider_id?: string | null;
  nickname?: string | null;
  name: string;
};
type ModelProvider = { id: string; name: string; is_active?: boolean };
type McpServer = { id: string; name: string; is_available?: boolean };
type PromptOption = { id: string; name: string; description?: string | null };

type PolicyModel = { completion_model_id: string; is_default: boolean };
type Policy = {
  models_restriction: { enabled: boolean; models: PolicyModel[]; provider_ids?: string[] | null };
  mcp_restriction: { enabled: boolean; server_ids: string[] };
  prompt_enforcement: { enabled: boolean; prompt_library_id?: string | null };
};

export type PolicyPageData = {
  intric: Intric;
  policy: Policy;
  models: { completionModels: CompletionModel[] };
  modelProviders?: ModelProvider[] | null;
  mcpSettings?: { items?: McpServer[] | null } | null;
  promptLibrary: { items: PromptOption[] };
};

export type BadgeVariant = "default" | "outline" | "destructive";

const EMPTY_POLICY: Policy = {
  models_restriction: { enabled: false, models: [], provider_ids: [] },
  mcp_restriction: { enabled: false, server_ids: [] },
  prompt_enforcement: { enabled: false, prompt_library_id: null }
};

export class PolicyDraft {
  // Assigned by `sync()`, which the page calls from an `$effect` on mount and
  // on every loader rerun — seeding here (rather than a constructor arg) avoids
  // statically capturing the initial `data` prop (state_referenced_locally).
  #intric!: Intric;

  // ---- Inputs (re-seeded from the loader on every data change) -------------
  #policy = $state<Policy>(EMPTY_POLICY);
  #allModels = $state<CompletionModel[]>([]);
  #allProviders = $state<ModelProvider[]>([]);
  #allMcpServers = $state<McpServer[]>([]);
  promptOptions = $state<PromptOption[]>([]);

  // ---- Editable state ------------------------------------------------------
  modelsEnabled = $state(false);
  modelSelections = new SvelteMap<string, ModelSelection>();
  providerSelections = new SvelteSet<string>();
  mcpEnabled = $state(false);
  mcpSelections = new SvelteSet<string>();
  promptEnabled = $state(false);
  selectedPromptId = $state<string | null>(null);

  // ---- Save lifecycle ------------------------------------------------------
  saving = $state(false);
  saveError = $state<string | null>(null);
  saveAnnouncement = $state("");
  pendingConfirm = $state<{ messages: string[]; submit: () => Promise<void> } | null>(null);

  /** Re-seed inputs, baseline and editable state from the loader. Reads only
      from `data` so it is safe to call inside an `$effect`. */
  sync(data: PolicyPageData) {
    this.#intric = data.intric;
    this.#policy = data.policy;
    this.#allModels = data.models.completionModels;
    this.#allProviders = (data.modelProviders ?? []).filter((p) => p.is_active);
    this.#allMcpServers = (data.mcpSettings?.items ?? []).filter((s) => s.is_available);
    this.promptOptions = data.promptLibrary.items;
    this.#seed(data.policy, data.models.completionModels);
  }

  #seed(policy: Policy, allModels: CompletionModel[]) {
    this.modelsEnabled = policy.models_restriction.enabled;
    this.modelSelections.clear();
    for (const model of allModels) {
      const existing = policy.models_restriction.models.find(
        (entry) => entry.completion_model_id === model.id
      );
      this.modelSelections.set(model.id, {
        selected: !!existing,
        isDefault: existing?.is_default ?? false
      });
    }
    this.providerSelections.clear();
    for (const pid of policy.models_restriction.provider_ids ?? []) {
      this.providerSelections.add(pid);
    }
    this.mcpEnabled = policy.mcp_restriction.enabled;
    this.mcpSelections.clear();
    for (const id of policy.mcp_restriction.server_ids) this.mcpSelections.add(id);
    this.promptEnabled = policy.prompt_enforcement.enabled;
    this.selectedPromptId = policy.prompt_enforcement.prompt_library_id ?? null;
    this.saveError = null;
  }

  // ---- Derived inputs ------------------------------------------------------
  allMcpServers = $derived(this.#allMcpServers);
  modelsByProvider = $derived.by(() => {
    const map = new SvelteMap<string | null, CompletionModel[]>();
    for (const model of this.#allModels) {
      const key = model.provider_id ?? null;
      const list = map.get(key);
      if (list) list.push(model);
      else map.set(key, [model]);
    }
    return map;
  });

  // ---- Derived selection state --------------------------------------------
  selectedModels = $derived(
    Array.from(this.modelSelections.entries())
      .filter(([, v]) => v.selected)
      .map(([id, v]) => ({ completion_model_id: id, is_default: v.isDefault }))
  );
  // Effective allowed set = explicit models ∪ all models from selected providers.
  effectiveModelIds = $derived.by(() => {
    const out = new SvelteSet<string>(
      this.selectedModels.map((entry) => entry.completion_model_id)
    );
    for (const pid of this.providerSelections) {
      for (const model of this.modelsByProvider.get(pid) ?? []) out.add(model.id);
    }
    return out;
  });
  defaultModelId = $derived(
    this.selectedModels.find((entry) => entry.is_default)?.completion_model_id ?? null
  );

  // ---- Dirty tracking (against the last-saved baseline) --------------------
  #initialModelIds = $derived(
    new SvelteSet(this.#policy.models_restriction.models.map((entry) => entry.completion_model_id))
  );
  #initialDefaultModelId = $derived(
    this.#policy.models_restriction.models.find((entry) => entry.is_default)?.completion_model_id ??
      null
  );
  #initialProviderIds = $derived(new SvelteSet(this.#policy.models_restriction.provider_ids ?? []));
  #initialMcpIds = $derived(new SvelteSet(this.#policy.mcp_restriction.server_ids));

  #modelsDirty = $derived(
    this.modelsEnabled !== this.#policy.models_restriction.enabled ||
      this.selectedModels.length !== this.#initialModelIds.size ||
      this.selectedModels.some((entry) => !this.#initialModelIds.has(entry.completion_model_id)) ||
      this.defaultModelId !== this.#initialDefaultModelId ||
      this.providerSelections.size !== this.#initialProviderIds.size ||
      Array.from(this.providerSelections).some((pid) => !this.#initialProviderIds.has(pid))
  );
  #mcpDirty = $derived(
    this.mcpEnabled !== this.#policy.mcp_restriction.enabled ||
      this.mcpSelections.size !== this.#initialMcpIds.size ||
      Array.from(this.mcpSelections).some((id) => !this.#initialMcpIds.has(id))
  );
  #promptDirty = $derived(
    this.promptEnabled !== this.#policy.prompt_enforcement.enabled ||
      (this.promptEnabled
        ? this.selectedPromptId !== (this.#policy.prompt_enforcement.prompt_library_id ?? null)
        : false)
  );
  dirty = $derived(this.#modelsDirty || this.#mcpDirty || this.#promptDirty);

  // ---- Validation ----------------------------------------------------------
  defaultValid = $derived(
    !this.modelsEnabled ||
      this.defaultModelId === null ||
      this.effectiveModelIds.has(this.defaultModelId)
  );
  canSave = $derived(
    this.dirty &&
      (!this.modelsEnabled || this.effectiveModelIds.size > 0) &&
      this.defaultValid &&
      (!this.promptEnabled || this.selectedPromptId !== null)
  );

  // ---- Summaries -----------------------------------------------------------
  modelsSummary = $derived.by(() => {
    if (!this.modelsEnabled) return m.governance_models_summary_inactive();
    const total = this.effectiveModelIds.size;
    if (total === 0) return m.governance_models_summary_none();
    if (total === 1) return m.governance_models_summary_single();
    const providerCount = this.providerSelections.size;
    if (providerCount === 0) return m.governance_models_summary_count({ count: total });
    return providerCount === 1
      ? m.governance_models_summary_count_provider_one({ count: total, providers: providerCount })
      : m.governance_models_summary_count_provider_other({
          count: total,
          providers: providerCount
        });
  });
  mcpSummary = $derived(
    !this.mcpEnabled
      ? m.governance_mcp_summary_inactive()
      : this.mcpSelections.size === 0
        ? m.governance_mcp_summary_none()
        : m.governance_mcp_summary_count({
            selected: this.mcpSelections.size,
            total: this.#allMcpServers.length
          })
  );
  promptSummary = $derived(
    !this.promptEnabled
      ? m.governance_prompt_summary_inactive()
      : !this.selectedPromptId
        ? m.governance_prompt_summary_none()
        : m.governance_prompt_summary_selected({
            name:
              this.promptOptions.find((p) => p.id === this.selectedPromptId)?.name ??
              m.governance_prompt_unknown()
          })
  );

  // ---- Helpers (arrow fields → safe to pass as props) ----------------------
  badgeVariant = (enabled: boolean, valid: boolean): BadgeVariant =>
    enabled ? (valid ? "default" : "destructive") : "outline";

  providerName = (pid: string | null): string =>
    pid === null
      ? m.governance_provider_other_models()
      : (this.#allProviders.find((p) => p.id === pid)?.name ?? m.governance_provider_unknown());

  // ---- Mutations -----------------------------------------------------------
  setSingleDefault = (id: string) => {
    // The default flag must travel on a row in `governance_policy_completion_models`,
    // so if the target is allowed only via a whitelisted provider, also flip its
    // `selected` bit on — that materialises the row at save time. The provider row
    // continues to cover all OTHER models from that provider unchanged.
    for (const [k, v] of this.modelSelections) {
      this.modelSelections.set(k, {
        selected: k === id ? true : v.selected,
        isDefault: k === id
      });
    }
  };

  toggleModelSelected = (id: string, on: boolean) => {
    const cur = this.modelSelections.get(id);
    if (!cur) return;
    this.modelSelections.set(id, { selected: on, isDefault: on && cur.isDefault });
    if (!on && cur.isDefault) {
      this.modelSelections.set(id, { selected: false, isDefault: false });
    }
  };

  toggleMcp = (id: string, on: boolean) => {
    if (on) this.mcpSelections.add(id);
    else this.mcpSelections.delete(id);
  };

  toggleProvider = (pid: string, on: boolean) => {
    if (on) {
      this.providerSelections.add(pid);
      // When a provider is whitelisted, individual selections under it become
      // redundant — clear them so the UI doesn't show duplicate state.
      for (const model of this.modelsByProvider.get(pid) ?? []) {
        const cur = this.modelSelections.get(model.id);
        if (cur) this.modelSelections.set(model.id, { selected: false, isDefault: cur.isDefault });
      }
    } else {
      this.providerSelections.delete(pid);
    }
  };

  // ---- Confirm + save ------------------------------------------------------
  #buildConfirmations = (): string[] => {
    const out: string[] = [];
    const initial = this.#policy;
    // "Locked single-model" UX only triggers when effective set is exactly one.
    if (
      this.modelsEnabled &&
      this.effectiveModelIds.size === 1 &&
      (!initial.models_restriction.enabled ||
        initial.models_restriction.models.length +
          (initial.models_restriction.provider_ids ?? []).length >
          1)
    ) {
      out.push(m.governance_confirm_models_hidden());
    }
    if (
      this.mcpEnabled &&
      this.mcpSelections.size === 0 &&
      (!initial.mcp_restriction.enabled || initial.mcp_restriction.server_ids.length !== 0)
    ) {
      out.push(m.governance_confirm_mcp_disabled());
    }
    if (this.promptEnabled && !initial.prompt_enforcement.enabled) {
      out.push(m.governance_confirm_prompt_forced());
    }
    return out;
  };

  #doSave = async () => {
    this.saving = true;
    this.saveError = null;
    this.saveAnnouncement = "";
    try {
      await this.#intric.governancePolicy.update({
        models_restriction: {
          enabled: this.modelsEnabled,
          models: this.selectedModels,
          provider_ids: Array.from(this.providerSelections)
        },
        mcp_restriction: {
          enabled: this.mcpEnabled,
          server_ids: Array.from(this.mcpSelections)
        },
        prompt_enforcement: {
          enabled: this.promptEnabled,
          prompt_library_id: this.promptEnabled ? this.selectedPromptId : null
        }
      });
      await invalidate("admin:governance-policy");
      this.pendingConfirm = null;
      this.saveAnnouncement = m.governance_save_success();
    } catch (e) {
      const err = e as { message?: string };
      this.saveError = err.message ?? m.governance_save_error();
      this.saveAnnouncement = m.governance_save_failure();
    } finally {
      this.saving = false;
    }
  };

  save = () => {
    const confirmations = this.#buildConfirmations();
    if (confirmations.length > 0) {
      this.pendingConfirm = { messages: confirmations, submit: this.#doSave };
    } else {
      this.#doSave();
    }
  };

  discard = () => {
    this.#seed(this.#policy, this.#allModels);
  };
}
