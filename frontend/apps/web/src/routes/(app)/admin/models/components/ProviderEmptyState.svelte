<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import { Button } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import { Plus, Layers } from "lucide-svelte";
  import { createEventDispatcher } from "svelte";
  import { fade } from "svelte/transition";

  export let providerId: string;

  const dispatch = createEventDispatcher<{
    addModel: { providerId: string };
  }>();

  function handleAddModel() {
    dispatch("addModel", { providerId });
  }
</script>

<div
  class="flex items-center gap-4 py-3 px-4 bg-surface-dimmer/40 rounded-lg border border-dashed border-dimmer/80"
  in:fade={{ duration: 200 }}
>
  <!-- Icon -->
  <div class="flex-shrink-0 p-3 rounded-lg bg-surface dark:bg-accent-dimmer border border-dimmer/50 dark:border-accent-default/20">
    <Layers class="w-5 h-5 text-muted/50 dark:text-accent-stronger" strokeWidth={1.5} />
  </div>

  <!-- Text -->
  <div class="flex-1 min-w-0">
    <p class="text-sm text-secondary font-medium">
      {m.no_models_in_provider()}
    </p>
    <p class="text-xs text-muted/70 mt-0.5">
      {m.add_model_to_get_started()}
    </p>
  </div>

  <!-- CTA -->
  <Button
    variant="outlined"
    padding="icon-leading"
    class="flex-shrink-0 text-xs h-8"
    on:click={handleAddModel}
  >
    <Plus class="w-3.5 h-3.5" />
    {m.add_model()}
  </Button>
</div>
