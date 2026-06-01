<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<!-- Needs to be a svelte 4 component for compatibility reasons with the table -->

<script lang="ts">
  import type { ConversationSparse } from "@intric/intric-js";
  import { getInsightsService } from "../InsightsService.svelte";
  import { Button } from "@intric/ui";

  const insights = getInsightsService();
  export let conversation: ConversationSparse;
  let isSelected = false;
  $: isSelected = insights.previewedConversation?.id === conversation.id;
</script>

<div class="flex w-full items-center justify-start">
  <Button
    type="button"
    on:click={() => insights.loadConversationPreview(conversation)}
    class="max-w-full"
    data-selected={isSelected}
    aria-pressed={isSelected}
  >
    <div
      class="bg-accent-dimmer absolute inset-0 z-[-1] hidden mix-blend-multiply"
      class:hidden={!isSelected}
    ></div>

    <span class="truncate overflow-ellipsis">
      {conversation.name}
    </span>
  </Button>
</div>
