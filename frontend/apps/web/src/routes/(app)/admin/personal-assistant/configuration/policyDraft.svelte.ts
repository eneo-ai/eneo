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
import { disabledToolIdsForSelectedServers } from "./mcpPolicy";

type ModelSelection = { selected: boolean; isDefault: boolean };
type CompletionModel = {
  id: string;
  provider_id?: string | null;
  nickname?: string | null;
  name: string;
  // Mirrors the backend's accept set: the policy PUT rejects any model whose
  // `can_access` is false (effectively-deprecated, locked, not org-enabled, …),
  // so the picker must only offer accessible models.
  can_access?: boolean;
};
type ModelProvider = { id: string; name: string; is_active?: boolean };
type McpTool = {
  id: string;
  name: string;
  description?: string | null;
  is_enabled_by_default?: boolean;
  removed_from_remote?: boolean;
};
type McpServer = {
  id: string;
  name: string;
  description?: string | null;
  is_available?: boolean;
  tools?: McpTool[] | null;
};
type PromptOption = { id: string; name: string; description?: string | null };

type PolicyModel = { completion_model_id: string; is_default: boolean };
type PolicyMcpServer = { mcp_server_id: string; is_default_enabled: boolean };
type Policy = {
  models_restriction: { enabled: boolean; models: PolicyModel[]; provider_ids?: string[] | null };
  mcp_restriction: {
    enabled: boolean;
    servers: PolicyMcpServer[];
    disabled_tool_ids?: string[] | null;
  };
  prompt_enforcement: { enabled: boolean; prompt_library_id?: string | null };
};

type PolicyUpdate = {
  models_restriction?: {
    enabled: boolean;
    models: PolicyModel[];
    provider_ids: string[];
  };
  mcp_restriction?: {
    enabled: boolean;
    servers: PolicyMcpServer[];
    disabled_tool_ids: string[];
  };
  prompt_enforcement?: {
    enabled: boolean;
    prompt_library_id: string | null;
  };
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
  mcp_restriction: { enabled: false, servers: [], disabled_tool_ids: [] },
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
  // Selected (allowed) servers → whether they start switched ON in users' chat.
  mcpSelections = new SvelteMap<string, { isDefaultEnabled: boolean }>();
  // Deny-set of tool ids switched off on allowed servers.
  disabledMcpToolIds = new SvelteSet<string>();
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
    // Only models the backend will accept (`can_access`); offering a
    // deprecated/locked model would make the policy PUT 400 on save.
    const selectableModels = data.models.completionModels.filter((m) => m.can_access);
    this.#allModels = selectableModels;
    this.#allProviders = (data.modelProviders ?? []).filter((p) => p.is_active);
    this.#allMcpServers = (data.mcpSettings?.items ?? []).filter((s) => s.is_available);
    this.promptOptions = data.promptLibrary.items;
    this.#seed(data.policy, selectableModels);
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
    // Skip grants whose server is no longer enabled — they cannot be rendered
    // or re-saved (see #selectableServerIds), so carrying them would only break
    // the save and inflate the summary count.
    for (const server of policy.mcp_restriction.servers) {
      if (!this.#selectableServerIds.has(server.mcp_server_id)) continue;
      this.mcpSelections.set(server.mcp_server_id, {
        isDefaultEnabled: server.is_default_enabled
      });
    }
    this.disabledMcpToolIds.clear();
    for (const id of policy.mcp_restriction.disabled_tool_ids ?? []) {
      if (!this.#selectableToolIds.has(id)) continue;
      this.disabledMcpToolIds.add(id);
    }
    this.promptEnabled = policy.prompt_enforcement.enabled;
    this.selectedPromptId = policy.prompt_enforcement.prompt_library_id ?? null;
    this.saveError = null;
  }

  // ---- Derived inputs ------------------------------------------------------
  // Servers/tools the policy can legally reference. `is_available` mirrors the
  // backend's tenant-enablement (it computes to `is_org_enabled`), and the PUT
  // is rejected for any server that is not currently enabled — so a grant for a
  // since-disabled server is dead: invisible in the section yet, if kept in the
  // payload, it 400s every save. We intersect seed, baseline and payload with
  // this set so an orphaned grant neither bricks saving nor shows a phantom
  // count; it is pruned from the policy on the next save that touches MCP.
  #selectableServerIds = $derived(new SvelteSet(this.#allMcpServers.map((s) => s.id)));
  #selectableToolIds = $derived(
    new SvelteSet(this.#allMcpServers.flatMap((s) => (s.tools ?? []).map((t) => t.id)))
  );
  // Only tools that exist on the remote and are globally enabled are offered —
  // globally disabled tools never run regardless of this policy.
  allMcpServers = $derived(
    this.#allMcpServers.map((server) => ({
      ...server,
      tools: (server.tools ?? []).filter(
        (tool) => tool.is_enabled_by_default !== false && !tool.removed_from_remote
      )
    }))
  );
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
  // Baselines intersect the selectable set so they match the filtered seed —
  // an orphaned (since-disabled) server in the saved policy must not register
  // as a pending change on a pristine load.
  #initialMcpServers = $derived(
    new SvelteMap(
      this.#policy.mcp_restriction.servers
        .filter((server) => this.#selectableServerIds.has(server.mcp_server_id))
        .map((server) => [server.mcp_server_id, server.is_default_enabled])
    )
  );
  #initialDisabledToolIds = $derived(
    new SvelteSet(
      (this.#policy.mcp_restriction.disabled_tool_ids ?? []).filter((id) =>
        this.#selectableToolIds.has(id)
      )
    )
  );

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
      this.mcpSelections.size !== this.#initialMcpServers.size ||
      Array.from(this.mcpSelections.entries()).some(
        ([id, v]) => this.#initialMcpServers.get(id) !== v.isDefaultEnabled
      ) ||
      this.disabledMcpToolIds.size !== this.#initialDisabledToolIds.size ||
      Array.from(this.disabledMcpToolIds).some((id) => !this.#initialDisabledToolIds.has(id))
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
  mcpValid = $derived(!this.mcpEnabled || this.mcpSelections.size > 0);
  canSave = $derived(
    this.dirty &&
      (!this.modelsEnabled || this.effectiveModelIds.size > 0) &&
      this.defaultValid &&
      this.mcpValid &&
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
    if (on) {
      this.mcpSelections.set(id, { isDefaultEnabled: true });
    } else {
      this.mcpSelections.delete(id);
      // Tool overrides only make sense for allowed servers — drop them so a
      // later re-select starts from "all tools on".
      // Use the unfiltered source so globally disabled / removed tools are
      // cleared too; those tools are intentionally hidden in the UI.
      const server = this.#allMcpServers.find((s) => s.id === id);
      for (const tool of server?.tools ?? []) this.disabledMcpToolIds.delete(tool.id);
    }
  };

  toggleMcpDefault = (id: string, on: boolean) => {
    if (this.mcpSelections.has(id)) this.mcpSelections.set(id, { isDefaultEnabled: on });
  };

  toggleMcpTool = (toolId: string, on: boolean) => {
    if (on) this.disabledMcpToolIds.delete(toolId);
    else this.disabledMcpToolIds.add(toolId);
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
    // Turning the grant OFF removes every MCP server from the personal
    // assistant (enabled+empty can no longer be saved).
    if (!this.mcpEnabled && initial.mcp_restriction.enabled) {
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
      const update: PolicyUpdate = {};
      if (this.#modelsDirty) {
        update.models_restriction = {
          enabled: this.modelsEnabled,
          models: this.selectedModels,
          provider_ids: Array.from(this.providerSelections)
        };
      }
      if (this.#mcpDirty) {
        update.mcp_restriction = {
          enabled: this.mcpEnabled,
          servers: Array.from(this.mcpSelections.entries()).map(([id, v]) => ({
            mcp_server_id: id,
            is_default_enabled: v.isDefaultEnabled
          })),
          disabled_tool_ids: disabledToolIdsForSelectedServers(
            this.#allMcpServers,
            this.mcpSelections.keys(),
            this.disabledMcpToolIds
          )
        };
      }
      if (this.#promptDirty) {
        update.prompt_enforcement = {
          enabled: this.promptEnabled,
          prompt_library_id: this.promptEnabled ? this.selectedPromptId : null
        };
      }
      await this.#intric.governancePolicy.update(update);
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
