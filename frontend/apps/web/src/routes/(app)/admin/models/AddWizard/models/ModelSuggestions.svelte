<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  Suggestion chips + "Browse all" Command palette.

  Up to four most-likely-relevant models are shown as one-click chips. A
  fifth chip toggles a shadcn Command (cmdk) palette over the full catalog
  with built-in keyboard navigation, filtering and ARIA semantics.
-->

<script lang="ts">
  import { Sparkles, Search } from "lucide-svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Command from "$lib/components/ui/command/index.js";
  import { m } from "$lib/paraglide/messages";
  import { formatTokens } from "./loadModels";
  import type { ModelInfo } from "./draft";

  let {
    models,
    selectedName,
    onSelect
  }: {
    models: ModelInfo[];
    selectedName: string;
    onSelect: (info: ModelInfo) => void;
  } = $props();

  let showAll = $state(false);

  const suggestions = $derived(models.slice(0, 4));
  const hasMore = $derived(models.length > 4);
</script>

{#if models.length > 0}
  <section class="flex flex-col gap-3" aria-label={m.suggested_models()}>
    <div class="text-muted-foreground flex items-center gap-2 text-sm">
      <Sparkles aria-hidden="true" />
      <span>{m.suggested_models()}</span>
    </div>

    <div class="flex flex-wrap gap-2">
      {#each suggestions as suggestion (suggestion.name)}
        {@const isSelected = selectedName === suggestion.name}
        <Button
          type="button"
          variant="outline"
          size="sm"
          class={isSelected
            ? "border-accent-default bg-accent-dimmer text-accent-stronger rounded-full"
            : "rounded-full"}
          onclick={() => onSelect(suggestion)}
          title={suggestion.display_name ? suggestion.name : undefined}
        >
          {suggestion.display_name ?? suggestion.name}
        </Button>
      {/each}
      {#if hasMore}
        <Button
          type="button"
          variant="outline"
          size="sm"
          class="rounded-full"
          onclick={() => (showAll = !showAll)}
          aria-expanded={showAll}
        >
          <Search aria-hidden="true" />
          {showAll ? m.close() : m.browse_all()}
        </Button>
      {/if}
    </div>

    {#if showAll}
      <div class="border-border bg-muted/30 overflow-hidden rounded-lg border">
        <Command.Root>
          <Command.Input placeholder={m.search_models()} />
          <Command.List class="max-h-64">
            <Command.Empty>{m.no_models_found()}</Command.Empty>
            {#each models as model (model.name)}
              <Command.Item
                value={`${model.name} ${model.display_name ?? ""}`}
                onSelect={() => {
                  onSelect(model);
                  showAll = false;
                }}
              >
                <div class="flex flex-col gap-0.5">
                  <span class="font-medium">{model.display_name ?? model.name}</span>
                  {#if model.display_name && model.display_name !== model.name}
                    <span class="text-muted-foreground font-mono text-xs">{model.name}</span>
                  {/if}
                  <span class="text-muted-foreground flex gap-3 text-xs">
                    {#if model.max_input_tokens}
                      <span
                        >{m.model_context_tokens({
                          tokens: formatTokens(model.max_input_tokens)
                        })}</span
                      >
                    {/if}
                    {#if model.supports_vision}<span>{m.capability_vision()}</span>{/if}
                    {#if model.supports_reasoning}<span>{m.reasoning()}</span>{/if}
                    {#if model.output_vector_size}
                      <span>{m.model_vector_dimensions({ size: model.output_vector_size })}</span>
                    {/if}
                  </span>
                </div>
              </Command.Item>
            {/each}
          </Command.List>
        </Command.Root>
      </div>
    {/if}
  </section>
{/if}
