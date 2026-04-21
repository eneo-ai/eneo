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
  class="bg-surface-dimmer/40 border-dimmer/80 flex items-center gap-4 rounded-lg border border-dashed px-4 py-3"
  in:fade={{ duration: 200 }}
>
  <!-- Icon -->
  <div
    class="bg-surface dark:bg-accent-dimmer border-dimmer/50 dark:border-accent-default/20 flex-shrink-0 rounded-lg border p-3"
  >
    <Layers class="text-muted/50 dark:text-accent-stronger h-5 w-5" strokeWidth={1.5} />
  </div>

  <!-- Text -->
  <div class="min-w-0 flex-1">
    <p class="text-secondary text-sm font-medium">
      {m.no_models_in_provider()}
    </p>
    <p class="text-muted/70 mt-0.5 text-xs">
      {m.add_model_to_get_started()}
    </p>
  </div>

  <!-- CTA -->
  <Button
    variant="outlined"
    padding="icon-leading"
    class="h-8 flex-shrink-0 text-xs"
    on:click={handleAddModel}
  >
    <Plus class="h-3.5 w-3.5" />
    {m.add_model()}
  </Button>
</div>
