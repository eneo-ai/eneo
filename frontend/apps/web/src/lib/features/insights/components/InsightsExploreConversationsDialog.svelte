<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconHistory } from "@eneo/icons/history";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import InsightsConversationTable from "./InsightsConversationTable.svelte";
  import InsightsConversationPreview from "./InsightsConversationPreview.svelte";
  import { m } from "$lib/paraglide/messages";
</script>

<Dialog.Root>
  <Dialog.Trigger>
    {#snippet child({ props })}
      <Button {...props} variant="outline" class="h-12 w-full"
        ><IconHistory />{m.explore_conversations()}</Button
      >
    {/snippet}
  </Dialog.Trigger>
  <Dialog.Content class={dialogLayout.content("large")} closeLabel={m.close()}>
    <Dialog.Header class={dialogLayout.header}>
      <Dialog.Title>{m.explore_conversations()}</Dialog.Title>
    </Dialog.Header>
    <div class={dialogLayout.body}>
      <div
        class="relative grid max-h-[75vh] min-h-[70vh] grid-cols-1 grid-rows-2 gap-3 overscroll-contain pb-2.5 md:gap-4 lg:grid-cols-2 lg:grid-rows-1"
      >
        <InsightsConversationTable></InsightsConversationTable>
        <InsightsConversationPreview></InsightsConversationPreview>
      </div>
    </div>
  </Dialog.Content>
</Dialog.Root>
