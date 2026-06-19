<script lang="ts">
  import { m } from "$lib/paraglide/messages";

  interface Props {
    /** Visible label (already prefixed if needed). */
    label: string;
    /** Full error message revealed on expand. */
    message: string;
    /** Optional native tooltip for the label. */
    tooltip?: string;
    /** Row border token; differs per container. */
    borderClass?: string;
  }

  let { label, message, tooltip, borderClass = "border-default" }: Props = $props();

  let expanded = $state(false);
</script>

<button
  class="{borderClass} hover:bg-hover-default flex w-full cursor-pointer flex-col border-b px-2 py-1.5 text-left last-of-type:border-b-0"
  aria-expanded={expanded}
  onclick={() => (expanded = !expanded)}
>
  <div class="flex w-full items-center justify-between gap-x-3 whitespace-nowrap">
    <div class="flex-shrink truncate pr-4" title={tooltip}>{label}</div>
    <div class="text-negative-default min-w-fit font-medium">{m.failed()}</div>
  </div>
  {#if expanded}
    <div class="text-secondary mt-1 w-full text-xs break-words whitespace-normal">
      {message}
    </div>
  {/if}
</button>
