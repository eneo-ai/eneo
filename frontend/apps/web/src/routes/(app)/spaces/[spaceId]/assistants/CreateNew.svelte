<script lang="ts">
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { getEneo } from "$lib/core/Eneo";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import TemplateCreateAssistant from "$lib/features/templates/components/assistants/TemplateCreateAssistant.svelte";
  import { getTemplateController } from "$lib/features/templates/TemplateController";
  import { IconAssistant } from "@eneo/icons/assistant";
  import { IconChevronDown } from "@eneo/icons/chevron-down";
  import { IconPeople } from "@eneo/icons/people";
  import { type Settings } from "@eneo/eneo-js";
  import { Button, Dialog, Dropdown } from "@eneo/ui";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { writable } from "svelte/store";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";

  let { data }: { data: { settings: Settings } } = $props();
  const uid = $props.id();

  const eneo = getEneo();

  const {
    state: { showCreateDialog: showCreateAssistantDialog }
  } = getTemplateController();

  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  const showCreateGroupChatDialog = writable(false);

  let newGroupChatName = $state("");
  let openGroupChatAfterCreation = $state(true);

  async function createNewGroupChat() {
    try {
      const newGroup = await eneo.groupChats.create({
        name: newGroupChatName,
        spaceId: $currentSpace.id
      });
      refreshCurrentSpace();
      if (openGroupChatAfterCreation) {
        goto(
          resolve(`/spaces/${$currentSpace.routeId}/group-chats/${newGroup.id}/edit?next=default`)
        );
      }
      newGroupChatName = "";
      $showCreateGroupChatDialog = false;
    } catch (error) {
      toastError(error);
    }
  }
</script>

<div class="flex gap-[1px]">
  <!-- eslint-disable-next-line @typescript-eslint/no-explicit-any -->
  {#snippet triggerSnippet(createAssistantTrigger: any)}
    <Button variant="primary" is={createAssistantTrigger} class="!rounded-r-none"
      >{m.create_assistant()}</Button
    >
  {/snippet}
  <TemplateCreateAssistant settings={data.settings} {triggerSnippet} />
  <Dropdown.Root gutter={2} arrowSize={0} placement="bottom-end">
    <Dropdown.Trigger asFragment let:trigger>
      <Button padding="icon" variant="primary" is={trigger} class="!rounded-l-none"
        ><IconChevronDown></IconChevronDown></Button
      >
    </Dropdown.Trigger>
    <Dropdown.Menu let:item>
      <Button is={item} onclick={() => ($showCreateAssistantDialog = true)}>
        <IconAssistant size="sm"></IconAssistant>
        {m.create_new_assistant()}</Button
      >
      <Button is={item} onclick={() => ($showCreateGroupChatDialog = true)}>
        <IconPeople size="sm"></IconPeople>
        {m.create_new_group_chat()}</Button
      >
    </Dropdown.Menu>
  </Dropdown.Root>
</div>

<Dialog.Root openController={showCreateGroupChatDialog}>
  <Dialog.Content width="dynamic">
    <Dialog.Section class="relative mt-2 -mb-0.5">
      <div class=" border-default flex w-full flex-col px-10 pt-12 pb-10">
        <h3 class="px-4 pb-1 text-2xl font-extrabold">{m.create_a_new_group_chat()}</h3>
        <p class="text-secondary max-w-[60ch] pr-36 pl-4">
          {m.group_chats_intro_text()}
        </p>
        <!-- <div class="h-8"></div> -->
        <div class=" border-dimmer mt-14 mb-4 border-t"></div>
        <div class="flex flex-col gap-1 pt-6 pb-4">
          <span class="px-4 pb-1 text-lg font-medium">{m.group_chat_name()}</span>
          <Field.Field>
            <Field.Label for={`${uid}-name`} class="sr-only">{m.group_chat_name()}</Field.Label>
            <Input
              id={`${uid}-name`}
              bind:value={newGroupChatName}
              class="!px-4 !py-6 !text-lg"
              placeholder="{m.name()}..."
              required
            />
          </Field.Field>
        </div>
      </div>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Field.Field orientation="horizontal" class="w-auto p-2">
        <Switch id={`${uid}-open-after`} bind:checked={openGroupChatAfterCreation} />
        <Field.Label for={`${uid}-open-after`}>
          {m.open_group_chat_editor_after_creation()}
        </Field.Label>
      </Field.Field>
      <div class="flex-grow"></div>
      <Button is={close}>{m.cancel()}</Button>
      <Button is={close} onclick={createNewGroupChat} variant="primary"
        >{m.create_group_chat()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
