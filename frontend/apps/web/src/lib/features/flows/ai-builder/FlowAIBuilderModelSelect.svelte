<script lang="ts">
  /* Picks the model that plans the flow — not the models the finished flow
     runs on, which the plan lists per step. The composer owns the trigger's
     appearance so this control sits level with "Bifoga filer". */
  import * as ModelSelector from "$lib/components/ai-elements/model-selector/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { groupModelsByVendor } from "$lib/features/ai-models/groupModels";
  import { m } from "$lib/paraglide/messages";

  import { getAIBuilderService } from "./FlowAIBuilderService.svelte.ts";

  const service = getAIBuilderService();

  const activeModel = $derived(service.effectiveModel);
  const groups = $derived(
    groupModelsByVendor(
      service.availableModels.map((model) => ({ ...model, provider_type: model.provider })),
      m.model_group_other()
    )
  );
</script>

<!-- Nothing renders while the read is in flight; the composer never waits on
     it. Every settled outcome says something, so an absent control is never
     left to look like an absent feature. -->
{#if service.modelLoadStatus === "failed"}
  <!-- Sending still works; only the choice is unavailable. -->
  <div class="flex min-w-0 items-center gap-1" role="alert">
    <span class="text-destructive max-w-44 truncate text-[0.8125rem]">
      {m.failed_to_load_models()}
    </span>
    <Button variant="destructive" size="xs" onclick={() => void service.retryModelLoad()}>
      {m.retry()}
    </Button>
  </div>
{:else if service.modelLoadStatus === "loaded" && service.availableModels.length === 0}
  <!-- The space offers no model this turn could run on. Saying so beats
       letting the user find out by sending. -->
  <span class="text-secondary max-w-72 truncate text-[0.8125rem]" role="status">
    {m.no_completion_model_description()}
  </span>
{:else if activeModel && service.availableModels.length > 1}
  <ModelSelector.Root>
    <ModelSelector.Trigger
      class="composer-control"
      aria-label={`${m.ai_builder_model_label()}: ${activeModel.name}`}
      title={m.ai_builder_model_usage_hint()}
      disabled={!service.canSendMessage}
    >
      <ModelSelector.Logo provider={activeModel.provider} />
      <ModelSelector.Name>{activeModel.name}</ModelSelector.Name>
    </ModelSelector.Trigger>
    <ModelSelector.Content align="start" class="w-72 max-w-[calc(100vw-2rem)]">
      <ModelSelector.Input placeholder={m.search_models()} />
      <ModelSelector.List>
        <ModelSelector.Empty>{m.no_models_found()}</ModelSelector.Empty>
        {#each groups as group (group.label)}
          <ModelSelector.Group heading={group.label}>
            {#each group.models as model (model.id)}
              <ModelSelector.Item
                value={`${model.id} ${model.name} ${group.label}`}
                selected={model.id === activeModel?.id}
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
{/if}
