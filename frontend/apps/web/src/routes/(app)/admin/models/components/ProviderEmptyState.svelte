<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import { Plus, Layers } from "lucide-svelte";
  import { fade } from "svelte/transition";

  let { providerId, onAddModel }: { providerId: string; onAddModel: (providerId: string) => void } =
    $props();
</script>

<div
  class="bg-surface-dimmer/40 border-dimmer/80 flex items-center gap-4 rounded-lg border border-dashed px-4 py-3"
  in:fade={{ duration: 200 }}
>
  <div
    class="bg-surface dark:bg-accent-dimmer border-dimmer/50 dark:border-accent-default/20 flex-shrink-0 rounded-lg border p-3"
  >
    <Layers class="text-muted/50 dark:text-accent-stronger h-5 w-5" strokeWidth={1.5} />
  </div>

  <div class="min-w-0 flex-1">
    <p class="text-secondary text-sm font-medium">
      {m.no_models_in_provider()}
    </p>
    <p class="text-muted/70 mt-0.5 text-xs">
      {m.add_model_to_get_started()}
    </p>
  </div>

  <Button variant="outline" size="sm" class="flex-shrink-0" onclick={() => onAddModel(providerId)}>
    <Plus />
    {m.add_model()}
  </Button>
</div>
