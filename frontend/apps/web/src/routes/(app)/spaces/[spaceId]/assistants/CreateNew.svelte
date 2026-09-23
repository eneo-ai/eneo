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
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
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
  {#snippet triggerSnippet(props: any)}
    <Button {...props} class="!rounded-r-none">{m.create_assistant()}</Button>
  {/snippet}
  <TemplateCreateAssistant settings={data.settings} {triggerSnippet} />
  <DropdownMenu.Root>
    <DropdownMenu.Trigger>
      {#snippet child({ props })}
        <Button {...props} size="icon" class="!rounded-l-none" aria-label={m.create_new()}
          ><IconChevronDown></IconChevronDown></Button
        >
      {/snippet}
    </DropdownMenu.Trigger>
    <DropdownMenu.Content align="end">
      <DropdownMenu.Item onSelect={() => ($showCreateAssistantDialog = true)}>
        <IconAssistant size="sm"></IconAssistant>
        {m.create_new_assistant()}
      </DropdownMenu.Item>
      <DropdownMenu.Item onSelect={() => ($showCreateGroupChatDialog = true)}>
        <IconPeople size="sm"></IconPeople>
        {m.create_new_group_chat()}
      </DropdownMenu.Item>
    </DropdownMenu.Content>
  </DropdownMenu.Root>
</div>

<Dialog.Root bind:open={$showCreateGroupChatDialog}>
  <Dialog.Content class={dialogLayout.content("dynamic")} closeLabel={m.close()}>
    <div class={dialogLayout.body}>
      <div class={[dialogLayout.section, "relative mt-2 -mb-0.5"]}>
        <div class=" border-default flex w-full flex-col px-10 pt-12 pb-10">
          <Dialog.Title class="px-4 pb-1 text-2xl font-extrabold"
            >{m.create_a_new_group_chat()}</Dialog.Title
          >
          <Dialog.Description class="text-secondary max-w-[60ch] pr-36 pl-4">
            {m.group_chats_intro_text()}
          </Dialog.Description>
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
      </div>
    </div>

    <Dialog.Footer class={dialogLayout.footer}>
      <Field.Field orientation="horizontal" class="w-auto p-2">
        <Switch id={`${uid}-open-after`} bind:checked={openGroupChatAfterCreation} />
        <Field.Label for={`${uid}-open-after`}>
          {m.open_group_chat_editor_after_creation()}
        </Field.Label>
      </Field.Field>
      <div class="flex-grow"></div>
      <Dialog.Close class={buttonVariants({ variant: "outline" })}>{m.cancel()}</Dialog.Close>
      <Dialog.Close class={buttonVariants()} onclick={createNewGroupChat}
        >{m.create_group_chat()}</Dialog.Close
      >
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
