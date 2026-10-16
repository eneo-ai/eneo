<script lang="ts">
  import IntegrationVendorIcon from "$lib/features/integrations/components/IntegrationVendorIcon.svelte";
  import type { IntegrationKnowledge } from "@eneo/eneo-js";

  interface Props {
    knowledge: IntegrationKnowledge;
    /** The item's documents page; without it the name is plain text. */
    href?: string;
    class?: string;
  }

  let { knowledge, href, class: customClass = "" }: Props = $props();

  let showOriginalName = $derived(
    knowledge.original_name && knowledge.original_name !== knowledge.name
  );
</script>

{#snippet name()}
  {knowledge.name}
  {#if showOriginalName}
    <span class="text-secondary">({knowledge.original_name})</span>
  {/if}
{/snippet}

<div class="flex w-full items-center justify-start {customClass} gap-2">
  <IntegrationVendorIcon size="sm" type={knowledge.integration_type}></IntegrationVendorIcon>
  <div class="min-w-0 flex-1">
    {#if href}
      <!-- eslint-disable svelte/no-navigation-without-resolve -- link is a typed prop passed from caller -->
      <a
        {href}
        class="focus-visible:ring-stronger block truncate overflow-ellipsis rounded font-medium hover:underline focus-visible:ring-2 focus-visible:outline-none"
      >
        {@render name()}
      </a>
      <!-- eslint-enable svelte/no-navigation-without-resolve -->
    {:else}
      <span class="block truncate overflow-ellipsis">
        {@render name()}
      </span>
    {/if}
  </div>
</div>
