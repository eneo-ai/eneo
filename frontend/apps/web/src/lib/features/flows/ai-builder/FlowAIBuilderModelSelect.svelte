<script lang="ts">
  import * as ModelSelector from "$lib/components/ai-elements/model-selector/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { groupModelsByVendor } from "$lib/features/ai-models/groupModels";
  import { m } from "$lib/paraglide/messages";
  import CircleAlert from "lucide-svelte/icons/circle-alert";
  import LoaderCircle from "lucide-svelte/icons/loader-circle";

  import { getAIBuilderService } from "./FlowAIBuilderService.svelte.ts";

  const service = getAIBuilderService();

  const selectedModel = $derived(
    service.availableModels.find((model) => model.id === service.selectedModelId) ?? null
  );
  const selectedLabel = $derived(selectedModel?.name ?? m.ai_builder_model_default());
  const accessibleLabel = $derived(`${m.ai_builder_model_label()}: ${selectedLabel}`);
  const selectableModels = $derived(
    service.availableModels.map((model) => ({ ...model, provider_type: model.provider }))
  );
  const modelGroups = $derived(groupModelsByVendor(selectableModels, m.model_group_other()));
</script>

{#if service.modelLoadStatus === "loading"}
  <Button
    variant="ghost"
    size="sm"
    disabled
    role="status"
    aria-live="polite"
    aria-busy="true"
    class="max-sm:h-11"
  >
    <LoaderCircle data-icon="inline-start" class="animate-spin" aria-hidden="true" />
    {m.loading()}
  </Button>
{:else if service.modelLoadStatus === "failed"}
  <div class="flex min-w-0 items-center gap-1" role="alert">
    <span class="text-destructive max-w-44 truncate text-xs">{m.failed_to_load_models()}</span>
    <Button
      variant="destructive"
      size="xs"
      onclick={() => void service.retryModelLoad()}
      class="max-sm:h-11"
    >
      {m.retry()}
    </Button>
  </div>
{:else if service.modelLoadStatus === "loaded" && service.availableModels.length > 1}
  <ModelSelector.Root>
    <ModelSelector.Trigger
      aria-label={accessibleLabel}
      title={m.ai_builder_model_usage_hint()}
      disabled={service.isCreating}
      class="h-7 max-w-[16rem] px-2 max-sm:h-11"
    >
      {#if selectedModel}
        <ModelSelector.Logo provider={selectedModel.provider} />
      {/if}
      <ModelSelector.Name>{selectedLabel}</ModelSelector.Name>
    </ModelSelector.Trigger>
    <ModelSelector.Content align="start" class="w-72 max-w-[calc(100vw-2rem)]">
      <ModelSelector.Input placeholder={m.search_models()} />
      <ModelSelector.List>
        <ModelSelector.Empty>{m.no_models_found()}</ModelSelector.Empty>
        {#each modelGroups as group (group.label)}
          <ModelSelector.Group heading={group.label}>
            {#each group.models as model (model.id)}
              <ModelSelector.Item
                value={`${model.id} ${model.name} ${group.label}`}
                selected={model.id === service.selectedModelId}
                onSelect={() => service.selectModel(model.id)}
              >
                <ModelSelector.Logo provider={model.provider} />
                <ModelSelector.Name>{model.name}</ModelSelector.Name>
              </ModelSelector.Item>
            {/each}
          </ModelSelector.Group>
        {/each}
      </ModelSelector.List>
    </ModelSelector.Content>
  </ModelSelector.Root>
{:else if service.modelLoadStatus === "loaded"}
  <Tooltip.Root>
    <Tooltip.Trigger>
      {#snippet child({ props })}
        <Button
          {...props}
          variant="ghost"
          size="sm"
          aria-disabled="true"
          aria-label={accessibleLabel}
          class="max-w-[16rem] max-sm:h-11"
          onclick={(event) => event.preventDefault()}
        >
          {#if selectedModel}
            <ModelSelector.Logo provider={selectedModel.provider} />
            <span class="truncate">{selectedLabel}</span>
          {:else}
            <CircleAlert data-icon="inline-start" aria-hidden="true" />
            <span class="truncate">{m.no_models_found()}</span>
          {/if}
        </Button>
      {/snippet}
    </Tooltip.Trigger>
    <Tooltip.Content side="top" sideOffset={6} class="max-w-64">
      {selectedModel ? m.ai_builder_model_only_one() : m.no_completion_model_description()}
      {#if selectedModel}
        <span class="text-muted-foreground mt-1 block">{m.ai_builder_model_usage_hint()}</span>
      {/if}
    </Tooltip.Content>
  </Tooltip.Root>
{/if}
