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
  // A space can carry models without naming a default, and the server then
  // falls back on its own. Naming the control beats naming a model we would
  // only be guessing at.
  const label = $derived(activeModel?.name ?? m.ai_builder_model_default());
  // One model is normally no choice at all. But when the server named no
  // default it may fall back to a model this list does not contain — an
  // inactive provider's — so picking the one active model explicitly is the
  // user's only way through. Offer it.
  const canChoose = $derived(
    service.availableModels.length > 1 ||
      (service.availableModels.length === 1 && service.defaultModelId === null)
  );
  const groups = $derived(
    groupModelsByVendor(
      service.availableModels.map((model) => ({ ...model, provider_type: model.provider })),
      m.model_group_other()
    )
  );
</script>

{#if service.modelLoadFailed}
  <!-- Saying nothing here would reproduce the very complaint this control
       answers: the model picker missing, with no reason given. -->
  <div class="flex min-w-0 items-center gap-1" role="alert">
    <span class="text-destructive max-w-44 truncate text-[0.8125rem]">
      {m.failed_to_load_models()}
    </span>
    <Button variant="destructive" size="xs" onclick={() => void service.retryModelLoad()}>
      {m.retry()}
    </Button>
  </div>
{:else if canChoose}
  <ModelSelector.Root>
    <ModelSelector.Trigger
      class="composer-control"
      aria-label={`${m.ai_builder_model_label()}: ${label}`}
      title={m.ai_builder_model_usage_hint()}
      disabled={!service.canSendMessage}
    >
      {#if activeModel}
        <ModelSelector.Logo provider={activeModel.provider} />
      {/if}
      <ModelSelector.Name>{label}</ModelSelector.Name>
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
