<script lang="ts">
  /* Picks the model that plans the flow — not the models the finished flow
     runs on, which the plan lists per step. The composer owns the trigger's
     appearance so this control sits level with "Bifoga filer". */
  import * as ModelSelector from "$lib/components/ai-elements/model-selector/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { groupModelsByVendor } from "$lib/features/ai-models/groupModels";
  import { m } from "$lib/paraglide/messages";

  import type { AIBuilderModel } from "./protocol";

  import { getAIBuilderService } from "./FlowAIBuilderService.svelte.ts";

  const service = getAIBuilderService();

  function availabilityReason(availability: AIBuilderModel["availability"]): string | null {
    const reasons = {
      ready: null,
      capacity_undeclared: m.ai_builder_model_capacity_undeclared_short(),
      capacity_too_small: m.ai_builder_model_capacity_too_small_short()
    } satisfies Record<AIBuilderModel["availability"]["state"], string | null>;
    return reasons[availability.state];
  }

  const activeModel = $derived(service.effectiveModel);
  const groups = $derived(
    groupModelsByVendor(
      service.availableModels.map((model) => ({ ...model, provider_type: model.provider })),
      m.model_group_other()
    )
  );
  const activeName = $derived(activeModel?.name ?? m.choose_a_completion_model());
  const blockReason = $derived(service.modelSendBlockMessage);
  // A choice is only offered while there is one to make or a way out is needed.
  const offersChoice = $derived(
    service.availableModels.length > 1 ||
      (service.availableModels.length > 0 && service.modelSendBlock !== null)
  );
</script>

<!-- The model a turn runs is always named, and every state says something:
     an absent control would look like an absent feature. -->
{#snippet shownModel()}
  {#if activeModel}
    <span
      class="text-primary flex h-9 min-w-0 items-center gap-1.5 px-2.5 text-sm font-medium"
      title={m.ai_builder_model_usage_hint()}
      data-testid="ai-builder-shown-model"
    >
      <span class="sr-only">{m.ai_builder_model_label()}:</span>
      <ModelSelector.Logo provider={activeModel.provider} />
      <span class="max-w-40 truncate">{activeModel.name}</span>
    </span>
  {/if}
{/snippet}

{#if service.modelLoadStatus === "loading"}
  {@render shownModel()}
  <span class="text-secondary text-[0.8125rem]" role="status">{m.ai_builder_models_loading()}</span>
{:else if service.modelLoadStatus === "failed"}
  <!-- No turn starts until a listing confirms the model; retrying is the way on. -->
  {@render shownModel()}
  <div class="flex min-w-0 items-center gap-1" role="alert">
    <span class="text-destructive max-w-44 truncate text-[0.8125rem]">
      {m.failed_to_load_models()}
    </span>
    <Button variant="destructive" size="xs" onclick={() => void service.retryModelLoad()}>
      {m.retry()}
    </Button>
  </div>
{:else if offersChoice}
  <!-- The trigger stays enabled while sending is blocked or a turn runs, so the
       way out sits next to the reason. -->
  <ModelSelector.Root>
    <ModelSelector.Trigger
      class="composer-control"
      aria-label={`${m.ai_builder_model_label()}: ${activeName}`}
      title={m.ai_builder_model_usage_hint()}
    >
      {#if activeModel}
        <ModelSelector.Logo provider={activeModel.provider} />
      {/if}
      <ModelSelector.Name>{activeName}</ModelSelector.Name>
    </ModelSelector.Trigger>
    <ModelSelector.Content align="start" class="w-72 max-w-[calc(100vw-2rem)]">
      <ModelSelector.Input placeholder={m.search_models()} />
      <ModelSelector.List>
        <ModelSelector.Empty>{m.no_models_found()}</ModelSelector.Empty>
        {#each groups as group (group.label)}
          <ModelSelector.Group heading={group.label}>
            {#each group.models as model (model.id)}
              {@const reason = availabilityReason(model.availability)}
              <ModelSelector.Item
                value={`${model.id} ${model.name} ${group.label}`}
                selected={model.id === activeModel?.id}
                disabled={reason !== null}
                onSelect={() => service.selectModel(model.id)}
              >
                <ModelSelector.Logo provider={model.provider} />
                <ModelSelector.Name>{model.name}</ModelSelector.Name>
                {#if reason}
                  <span class="text-secondary ml-auto shrink-0 text-xs">
                    {reason}
                  </span>
                {/if}
              </ModelSelector.Item>
            {/each}
          </ModelSelector.Group>
        {/each}
      </ModelSelector.List>
    </ModelSelector.Content>
  </ModelSelector.Root>
{:else}
  <!-- One ready model needs no choice, but it is still the model that runs. -->
  {@render shownModel()}
{/if}
{#if service.modelLoadStatus === "loaded" && blockReason}
  <span class="text-secondary max-w-72 truncate text-[0.8125rem]" role="status" title={blockReason}>
    {blockReason}
  </span>
{/if}
