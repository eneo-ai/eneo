<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconHistory } from "@intric/icons/history";
  import { Dialog, Button } from "@intric/ui";
  import InsightsConversationTable from "./InsightsConversationTable.svelte";
  import InsightsConversationPreview from "./InsightsConversationPreview.svelte";
  import { m } from "$lib/paraglide/messages";
</script>

<Dialog.Root>
  <Dialog.Trigger asFragment let:trigger>
    <Button is={trigger} variant="outlined" class="h-12 w-full"
      ><IconHistory />{m.explore_conversations()}</Button
    >
  </Dialog.Trigger>
  <Dialog.Content width="large">
    <Dialog.Title>{m.explore_conversations()}</Dialog.Title>
    <div
      class="relative grid max-h-[70vh] min-h-[70vh] grid-cols-1 grid-rows-2 gap-4 pb-2.5 lg:grid-cols-2 lg:grid-rows-1"
    >
      <InsightsConversationTable></InsightsConversationTable>
      <InsightsConversationPreview></InsightsConversationPreview>
    </div>
  </Dialog.Content>
</Dialog.Root>
