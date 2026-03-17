<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconHistory } from "@intric/icons/history";
  import { Dialog, Button } from "@intric/ui";
  import { writable } from "svelte/store";
  import InsightsConversationTable from "./InsightsConversationTable.svelte";
  import InsightsConversationPreview from "./InsightsConversationPreview.svelte";
  import { m } from "$lib/paraglide/messages";

  const showExploreDialog = writable(false);
</script>

<Dialog.Root openController={showExploreDialog}>
  <Button
    type="button"
    variant="outlined"
    class="h-12 w-full"
    aria-haspopup="dialog"
    aria-expanded={$showExploreDialog}
    on:click={() => showExploreDialog.set(true)}
    ><IconHistory />{m.explore_conversations()}</Button
  >
  <Dialog.Content width="large">
    <Dialog.Title>{m.explore_conversations()}</Dialog.Title>
    <div
      class="relative grid max-h-[75vh] min-h-[70vh] grid-cols-1 grid-rows-2 gap-3 overscroll-contain pb-2.5 md:gap-4 lg:grid-cols-2 lg:grid-rows-1"
    >
      <InsightsConversationTable></InsightsConversationTable>
      <InsightsConversationPreview></InsightsConversationPreview>
    </div>
  </Dialog.Content>
</Dialog.Root>
