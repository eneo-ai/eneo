<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.

    shadcn model selector for the chat input toolbar: policy-filtered models,
    a locked label when the policy pins a single model, and a plain label when
    only one model is available. Switching updates the personal space's default
    assistant. Only meaningful for the default assistant — callers gate on
    partner.type.
-->
<script lang="ts">
  import * as Select from "$lib/components/ui/select/index.js";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { sortModels } from "$lib/features/ai-models/sortModels";
  import { m } from "$lib/paraglide/messages";
  import { Lock } from "lucide-svelte";

  const {
    state: { currentSpace },
    updateDefaultAssistant
  } = getSpacesManager();

  // Only rendered when chat.partner.type === "default-assistant", which
  // guarantees the personal space's default_assistant is present.
  const defaultAssistant = $derived($currentSpace.default_assistant!);
  const effectiveConfig = $derived(defaultAssistant.effective_config);

  // When the admin policy locks the model to one option, show the locked name
  // instead of a picker.
  const lockedModel = $derived(
    effectiveConfig?.models_enforced && effectiveConfig.locked_model
      ? ($currentSpace.completion_models.find(
          (model) => model.id === effectiveConfig.locked_model?.id
        ) ?? effectiveConfig.locked_model)
      : null
  );
  const policyAllowedModelIds = $derived(
    effectiveConfig?.models_enforced
      ? new Set(effectiveConfig.available_models.map((model) => model.id))
      : null
  );
  const visibleModels = $derived(
    sortModels(
      policyAllowedModelIds
        ? $currentSpace.completion_models.filter((model) => policyAllowedModelIds.has(model.id))
        : $currentSpace.completion_models
    )
  );

  const selectedModel = $derived.by(() => {
    const current = defaultAssistant.completion_model;
    if (!effectiveConfig?.models_enforced) return current;
    if (current && policyAllowedModelIds?.has(current.id)) return current;
    return (
      effectiveConfig.default_model ?? effectiveConfig.locked_model ?? visibleModels[0] ?? null
    );
  });
  const selectedId = $derived(selectedModel?.id ?? "");
  const selectedLabel = $derived(selectedModel?.nickname ?? m.select_a_model());

  function selectModel(id: string) {
    if (!id || id === selectedId) return;
    // Persist the model on the personal default assistant. The chat page keeps
    // the chat partner synced with SpacesManager, so no manual partner update
    // is needed here.
    updateDefaultAssistant({ completionModel: { id } });
  }
</script>

{#if lockedModel}
  <div
    class="text-muted-foreground flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm"
    title={m.governance_locked_by_admin()}
  >
    <Lock class="size-3.5" aria-hidden="true" />
    <span class="text-foreground max-w-[10rem] truncate font-medium">{lockedModel.nickname}</span>
  </div>
{:else if visibleModels.length <= 1}
  <div class="rounded-lg px-2.5 py-1.5 text-sm" title={m.choose_a_completion_model()}>
    <span class="max-w-[12rem] truncate font-medium">{selectedLabel}</span>
  </div>
{:else}
  <Select.Root type="single" value={selectedId} onValueChange={selectModel}>
    <Select.Trigger
      class="h-9 max-w-[13rem] gap-1.5 rounded-lg border-0 shadow-none"
      aria-label={m.choose_a_completion_model()}
    >
      <span class="truncate">{selectedLabel}</span>
    </Select.Trigger>
    <Select.Content align="end">
      {#each visibleModels as model (model.id)}
        <Select.Item value={model.id ?? ""} label={model.nickname ?? ""}>
          {model.nickname}
        </Select.Item>
      {/each}
    </Select.Content>
  </Select.Root>
{/if}
