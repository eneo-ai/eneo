<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconAssistant } from "@eneo/icons/assistant";
  import { IconTrash } from "@eneo/icons/trash";
  import type { GroupChat } from "@eneo/eneo-js";
  import { Button } from "@eneo/ui";
  import GroupChatAssistantListAddDialog from "./GroupChatAssistantListAddDialog.svelte";
  import GroupChatAssistantListEditDialog from "./GroupChatAssistantListEditDialog.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";

  type AssistantTool = GroupChat["tools"]["assistants"][number];
  type Props = {
    selectedAssistants: GroupChat["tools"]["assistants"];
  };

  let { selectedAssistants = $bindable([]) }: Props = $props();

  const {
    state: { currentSpace }
  } = getSpacesManager();

  const availableAssistants: AssistantTool[] = $derived.by(() => {
    return $currentSpace.applications.assistants
      .filter(({ id }) => !selectedAssistants.some(({ id: _id }) => id === _id))
      .map(({ name, id, description }) => {
        return {
          id,
          handle: name,
          default_description: description ?? null,
          user_description: null
        };
      });
  });

  function updateAssistant(updatedAssistant: AssistantTool) {
    selectedAssistants = selectedAssistants.map((currAssistant) =>
      currAssistant.id === updatedAssistant.id ? updatedAssistant : currAssistant
    );
  }

  function addAssistantToGroup(assistant: AssistantTool) {
    // we need to assign a value to trigger reactivity
    selectedAssistants = [...selectedAssistants, assistant];
  }

  function removeFromGroup(assistant: { id: string }) {
    // selected assistants is bound to a store in the GroupChatEditop,
    // we need to assign a value to trigger reactivity
    selectedAssistants = selectedAssistants.filter(({ id }) => id !== assistant.id);
  }
</script>

<div class="flex flex-col">
  {#each selectedAssistants as assistant (assistant.id)}
    <div class="item">
      <IconAssistant></IconAssistant>
      <span class="truncate px-2">
        {assistant.handle}
      </span>
      <div class="flex-grow"></div>
      <GroupChatAssistantListEditDialog {assistant} {updateAssistant}
      ></GroupChatAssistantListEditDialog>
      <Button
        variant="destructive"
        padding="icon"
        on:click={() => {
          removeFromGroup(assistant);
        }}><IconTrash /></Button
      >
    </div>
  {/each}
</div>

<div class="h-2"></div>

<GroupChatAssistantListAddDialog {addAssistantToGroup} {availableAssistants}
></GroupChatAssistantListAddDialog>

<style lang="postcss">
  @reference "@eneo/ui/styles";
  .item {
    @apply border-default bg-primary hover:bg-hover-dimmer flex h-16 w-full items-center gap-2 border-b px-4;
  }
</style>
