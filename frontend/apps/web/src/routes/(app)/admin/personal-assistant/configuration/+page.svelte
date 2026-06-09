<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import McpRestrictionSection from "./McpRestrictionSection.svelte";
  import ModelRestrictionSection from "./ModelRestrictionSection.svelte";
  import PolicyConfirmDialog from "./PolicyConfirmDialog.svelte";
  import PolicySaveBar from "./PolicySaveBar.svelte";
  import PromptEnforcementSection from "./PromptEnforcementSection.svelte";
  import { PolicyDraft } from "./policyDraft.svelte";

  let { data } = $props();

  // All draft/dirty/validation/save logic lives in the store; this page is wiring.
  const draft = new PolicyDraft();
  // Seed on mount and re-seed to the new baseline whenever the loader reruns
  // (e.g. after a save followed by invalidate()). `sync` reads only from `data`,
  // so there is no read-after-write cycle.
  $effect(() => {
    draft.sync(data);
  });
</script>

<svelte:head>
  <title>{m.governance_page_title()}</title>
</svelte:head>

<div class="flex-1 overflow-y-auto px-6 pt-6">
  <Settings.Page>
    <div class="space-y-6 pb-32">
      <ModelRestrictionSection
        bind:modelsEnabled={draft.modelsEnabled}
        modelsByProvider={draft.modelsByProvider}
        modelSelections={draft.modelSelections}
        providerSelections={draft.providerSelections}
        effectiveModelIds={draft.effectiveModelIds}
        defaultModelId={draft.defaultModelId}
        modelsSummary={draft.modelsSummary}
        defaultValid={draft.defaultValid}
        badgeVariant={draft.badgeVariant}
        providerName={draft.providerName}
        setSingleDefault={draft.setSingleDefault}
        toggleModelSelected={draft.toggleModelSelected}
        toggleProvider={draft.toggleProvider}
      />
      <McpRestrictionSection
        bind:mcpEnabled={draft.mcpEnabled}
        allMcpServers={draft.allMcpServers}
        mcpSelections={draft.mcpSelections}
        disabledMcpToolIds={draft.disabledMcpToolIds}
        mcpSummary={draft.mcpSummary}
        mcpValid={draft.mcpValid}
        badgeVariant={draft.badgeVariant}
        toggleMcp={draft.toggleMcp}
        toggleMcpDefault={draft.toggleMcpDefault}
        toggleMcpTool={draft.toggleMcpTool}
      />
      <PromptEnforcementSection
        bind:promptEnabled={draft.promptEnabled}
        bind:selectedPromptId={draft.selectedPromptId}
        promptOptions={draft.promptOptions}
        promptSummary={draft.promptSummary}
        badgeVariant={draft.badgeVariant}
      />
    </div>
  </Settings.Page>
</div>

<!-- Live region for save status (announced by screen readers) -->
<div role="status" aria-live="polite" class="sr-only">{draft.saveAnnouncement}</div>

<PolicySaveBar
  dirty={draft.dirty}
  saveError={draft.saveError}
  canSave={draft.canSave}
  saving={draft.saving}
  onDiscard={draft.discard}
  onSave={draft.save}
/>
<PolicyConfirmDialog bind:pendingConfirm={draft.pendingConfirm} saving={draft.saving} />
