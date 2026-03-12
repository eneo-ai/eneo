<script lang="ts">
  import IntegrationVendorIcon from "$lib/features/integrations/components/IntegrationVendorIcon.svelte";
  import type { IntegrationKnowledge } from "@intric/intric-js";

  interface Props {
    knowledge: IntegrationKnowledge;
    class?: string;
  }

  let { knowledge, class: customClass = "" }: Props = $props();

  let showOriginalName = $derived(
    knowledge.original_name && knowledge.original_name !== knowledge.name
  );
</script>

<div class="flex w-full items-center justify-start {customClass} gap-2">
  <IntegrationVendorIcon size="sm" type={knowledge.integration_type}></IntegrationVendorIcon>
  <div class="min-w-0 flex-1">
    <span class="truncate overflow-ellipsis block">
      {knowledge.name}
      {#if showOriginalName}
        <span class="text-secondary">({knowledge.original_name})</span>
      {/if}
    </span>
  </div>
</div>
