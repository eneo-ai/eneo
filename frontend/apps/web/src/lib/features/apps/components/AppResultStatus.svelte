<script lang="ts">
  import { IconCheck } from "@intric/icons/check";
  import { IconCancel } from "@intric/icons/cancel";
  import { Tooltip } from "@intric/ui";
  import type { AppRun } from "@intric/intric-js";
  export let run: Pick<AppRun, "status">;
  export let variant: "icon" | "full" = "icon";
  import { m } from "$lib/paraglide/messages";
  $: cssClass = run.status.replace(" ", "-");
</script>

<div class="{cssClass} flex min-h-8 min-w-8 items-center justify-center rounded-lg px-4">
  {#if run.status === "complete"}
    <Tooltip text={m.finished()}>
      <IconCheck />
    </Tooltip>
  {:else if run.status === "in progress"}
    <Tooltip text={m.running()}>
      <div class="relative h-3 w-3">
        <span class="bg-accent-default absolute h-full w-full animate-ping rounded-full"></span>
        <span class="bg-accent-default absolute h-full w-full rounded-full"></span>
      </div>
    </Tooltip>
  {:else if run.status === "failed"}
    <Tooltip text={m.failed()}>
      <IconCancel />
    </Tooltip>
  {/if}
  {#if variant === "full"}
    <span class="p-2 capitalize">{run.status}</span>
  {/if}
</div>

<style lang="postcss">
  @reference "@intric/ui/styles";
  .complete {
    @apply bg-positive-dimmer text-positive-stronger;
  }
  .failed {
    @apply bg-negative-dimmer text-negative-stronger;
  }
  .in-progress {
    @apply bg-accent-dimmer text-accent-stronger;
  }
  .queued {
    @apply bg-secondary text-secondary;
  }
</style>
