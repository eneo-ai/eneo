<script lang="ts">
  import { IconCheck } from "@eneo/icons/check";
  import { IconCancel } from "@eneo/icons/cancel";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import type { AppRun } from "@eneo/eneo-js";
  export let run: Pick<AppRun, "status">;
  export let variant: "icon" | "full" = "icon";
  import { m } from "$lib/paraglide/messages";
  $: cssClass = run.status.replace(" ", "-");
  $: statusTooltip =
    run.status === "complete"
      ? m.finished()
      : run.status === "in progress"
        ? m.running()
        : run.status === "failed"
          ? m.failed()
          : undefined;
</script>

<div class="{cssClass} flex min-h-8 min-w-8 items-center justify-center rounded-lg px-4">
  {#if statusTooltip}
    <Tooltip.Root>
      <Tooltip.Trigger>
        {#snippet child({ props })}
          <!-- Not a tab stop: the status is also rendered inside result links. -->
          {@const { tabindex: _tabindex, ...triggerProps } = props}
          <div {...triggerProps}>
            {#if run.status === "complete"}
              <IconCheck />
            {:else if run.status === "in progress"}
              <div class="relative h-3 w-3">
                <span class="bg-accent-default absolute h-full w-full animate-ping rounded-full"
                ></span>
                <span class="bg-accent-default absolute h-full w-full rounded-full"></span>
              </div>
            {:else}
              <IconCancel />
            {/if}
            {#if variant === "icon"}
              <span class="sr-only">{statusTooltip}</span>
            {/if}
          </div>
        {/snippet}
      </Tooltip.Trigger>
      <Tooltip.Content>{statusTooltip}</Tooltip.Content>
    </Tooltip.Root>
  {/if}
  {#if variant === "full"}
    <span class="p-2">
      {#if run.status === "complete"}
        {m.complete()}
      {:else if run.status === "in progress"}
        {m.in_progress()}
      {:else if run.status === "failed"}
        {m.failed()}
      {:else if run.status === "queued"}
        {m.queued()}
      {:else}
        {run.status}
      {/if}
    </span>
  {/if}
</div>

<style lang="postcss">
  @reference "@eneo/ui/styles";
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
