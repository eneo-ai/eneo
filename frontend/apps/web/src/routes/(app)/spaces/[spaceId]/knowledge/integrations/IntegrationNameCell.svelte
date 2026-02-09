<script lang="ts">
  import IntegrationVendorIcon from "$lib/features/integrations/components/IntegrationVendorIcon.svelte";
  import { m } from "$lib/paraglide/messages";
  import type { IntegrationKnowledge } from "@intric/intric-js";

  interface Props {
    knowledge: IntegrationKnowledge;
    wrapperName?: string;
    class?: string;
  }

  let { knowledge, wrapperName, class: customClass = "" }: Props = $props();

  let showOriginalName = $derived(
    knowledge.original_name && knowledge.original_name !== knowledge.name
  );

  type MessageFn = (args?: Record<string, unknown>) => string;

  function resolveInWrapperLabel(name: string): string {
    const maybeFn = (m as unknown as Record<string, MessageFn | undefined>)["sharepoint_in_wrapper"];
    if (typeof maybeFn === "function") {
      return maybeFn({ name });
    }
    return name;
  }
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
    {#if wrapperName}
      <div class="mt-0.5 flex min-w-0 items-center gap-1 text-xs text-secondary">
        <span
          aria-hidden="true"
          class="border-label-default inline-block h-3 w-3 shrink-0 rounded-bl border-b border-l"
        ></span>
        <span class="truncate">{resolveInWrapperLabel(wrapperName)}</span>
      </div>
    {/if}
  </div>
</div>
