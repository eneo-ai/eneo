<script lang="ts">
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { IconXMark } from "@eneo/icons/x-mark";
  import { m } from "$lib/paraglide/messages";

  let {
    flowName,
    stepCount,
    isDirty,
    isSubmitting,
    onRequestClose
  }: {
    flowName: string;
    stepCount: number;
    isDirty: boolean;
    isSubmitting: boolean;
    onRequestClose: () => void;
  } = $props();
</script>

<header class="border-default/60 shrink-0 border-b px-4 py-4 sm:px-6 sm:py-5 lg:px-8">
  <div class="flex items-start justify-between gap-4">
    <div class="min-w-0">
      <Dialog.Title class="text-primary text-lg font-semibold tracking-tight sm:text-xl">
        {m.flow_run_trigger()}
      </Dialog.Title>
      <Dialog.Description
        class="text-secondary mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm"
      >
        <span class="text-primary truncate font-medium">{flowName}</span>
        {#if stepCount > 0}
          <Badge variant="outline" class="h-5 text-xs font-medium tabular-nums">
            {m.flow_run_step_count({ count: String(stepCount) })}
          </Badge>
        {/if}
      </Dialog.Description>
    </div>
    {#if isDirty && !isSubmitting}
      <Button
        variant="ghost"
        size="icon-sm"
        class="text-muted hover:text-primary -mt-1 -mr-1 shrink-0"
        aria-label={m.flow_run_trigger_close()}
        onclick={onRequestClose}
      >
        <IconXMark />
      </Button>
    {:else}
      <Dialog.Close>
        {#snippet child({ props })}
          <Button
            {...props}
            variant="ghost"
            size="icon-sm"
            class="text-muted hover:text-primary -mt-1 -mr-1 shrink-0"
            aria-label={m.flow_run_trigger_close()}
          >
            <IconXMark />
          </Button>
        {/snippet}
      </Dialog.Close>
    {/if}
  </div>
</header>
