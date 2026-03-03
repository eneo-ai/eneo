<script lang="ts">
  import { IconInfo } from "@intric/icons/info";
  import { fade } from "svelte/transition";
  import { m } from "$lib/paraglide/messages";

  export let errors: Map<string, string[]>;

  $: errorCount = errors.size;
  $: hasErrors = errorCount > 0;
</script>

{#if hasErrors}
  <div
    class="bg-negative-dimmer border-negative-default/40 flex items-center gap-2 border-b px-4 py-2 text-sm text-negative-stronger"
    transition:fade={{ duration: 200 }}
  >
    <IconInfo class="size-4 shrink-0" />
    <span>{m.flow_validation_issues({ count: String(errorCount) })}</span>
  </div>
{/if}
