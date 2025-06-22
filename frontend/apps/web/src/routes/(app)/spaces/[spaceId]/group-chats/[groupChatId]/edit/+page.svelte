<script lang="ts">
  import { Page, Settings } from "$lib/components/layout";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager.js";
  import { Button, Input } from "@intric/ui";
  import { afterNavigate, beforeNavigate } from "$app/navigation";
  import { fade } from "svelte/transition";
  import { page } from "$app/state";
  import { initGroupChatEditor } from "$lib/features/group-chats/GroupChatEditor.js";
  import GroupChatAssistantList from "$lib/features/group-chats/components/GroupChatAssistantList.svelte";
  import PublishingSetting from "$lib/features/publishing/components/PublishingSetting.svelte";
  import { getChatQueryParams } from "$lib/features/chat/getChatQueryParams.js";
  import { m } from "$lib/paraglide/messages";

  export let data;

  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  const {
    state: { resource, update, currentChanges, isSaving },
    saveChanges,
    discardChanges
  } = initGroupChatEditor({
    groupChat: data.groupChat,
    intric: data.intric,
    onUpdateDone() {
      refreshCurrentSpace("applications");
    }
  });

  beforeNavigate((navigate) => {
    if (
      $currentChanges.hasUnsavedChanges &&
      !confirm(m.unsaved_changes_warning())
    ) {
      navigate.cancel();
      return;
    }
    // Discard changes that have been made, this is only important so we delete uploaded
    // files that have not been saved to the assistant
    discardChanges();
  });

  let showSavesChangedNotice = false;

  // TODO
  let previousRoute = `/spaces/${$currentSpace.routeId}/chat/?${getChatQueryParams({ chatPartner: data.groupChat, tab: "chat" })}`;
  afterNavigate(({ from }) => {
    if (page.url.searchParams.get("next") === "default") return;
    if (from) previousRoute = from.url.toString();
  });
</script>

<svelte:head>
  <title
    >Eneo.ai – {data.currentSpace.personal ? m.personal() : data.currentSpace.name} – {$resource.name}</title
  >
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title
      parent={{
        title: $resource.name,
        href: `/spaces/${$currentSpace.routeId}/chat/?${getChatQueryParams({ chatPartner: data.groupChat, tab: "chat" })}`
      }}
      title={m.edit()}
    ></Page.Title>

    <Page.Flex>
      {#if $currentChanges.hasUnsavedChanges}
        <Button
          variant="destructive"
          disabled={$isSaving}
          on:click={() => {
            discardChanges();
          }}>{m.discard_all_changes()}</Button
        >

        <Button
          variant="positive"
          class="w-32"
          on:click={async () => {
            await saveChanges();
            showSavesChangedNotice = true;
            setTimeout(() => {
              showSavesChangedNotice = false;
            }, 5000);
          }}>{$isSaving ? m.saving() : m.save_changes()}</Button
        >
      {:else}
        {#if showSavesChangedNotice}
          <p class="text-positive-stronger px-4" transition:fade>{m.all_changes_saved()}</p>
        {/if}
        <Button variant="primary" class="w-32" href={previousRoute}>{m.done()}</Button>
      {/if}
    </Page.Flex>
  </Page.Header>

  <Page.Main>
    <Settings.Page>
      <Settings.Group title={m.general()}>
        <Settings.Row
          title={m.name()}
          description={m.give_group_chat_name_displayed_to_users()}
          hasChanges={$currentChanges.diff.name !== undefined}
          revertFn={() => {
            discardChanges("name");
          }}
          let:aria
        >
          <input
            type="text"
            {...aria}
            bind:value={$update.name}
            class="border-default bg-primary ring-default rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
          />
        </Settings.Row>
      </Settings.Group>

      <Settings.Group title={m.group_settings()}>
        <Settings.Row
          title={m.assistants()}
          description={m.assistants_will_be_able_to_answer_questions()}
          hasChanges={$currentChanges.diff.tools?.assistants !== undefined}
          revertFn={() => {
            $update.tools.assistants = $resource.tools.assistants;
          }}
        >
          <GroupChatAssistantList bind:selectedAssistants={$update.tools.assistants} />
        </Settings.Row>
      </Settings.Group>

      <Settings.Group title={m.advanced_settings()}>
        <Settings.Row
          title={m.mentions()}
          description={m.allow_users_to_select_assistant_by_mentioning()}
          hasChanges={$currentChanges.diff.allow_mentions !== undefined}
          revertFn={() => {
            discardChanges("allow_mentions");
          }}
        >
          <div class="border-default flex h-14 border-b py-2">
            <Input.RadioSwitch
              bind:value={$update.allow_mentions}
              labelTrue={m.enable_mentions()}
              labelFalse={m.disable_mentions()}
            ></Input.RadioSwitch>
          </div>
        </Settings.Row>

        <Settings.Row
          title={m.response_labels()}
          description={m.show_answering_assistant_name_next_to_response()}
          hasChanges={$currentChanges.diff.show_response_label !== undefined}
          revertFn={() => {
            discardChanges("show_response_label");
          }}
        >
          <div class="border-default flex h-14 border-b py-2">
            <Input.RadioSwitch
              bind:value={$update.show_response_label}
              labelTrue={m.show_labels()}
              labelFalse={m.hide_labels()}
            ></Input.RadioSwitch>
          </div>
        </Settings.Row>
      </Settings.Group>

      {#if data.groupChat.permissions?.some((permission) => permission === "insight_toggle" || permission === "publish")}
        <Settings.Group title={m.publishing()}>
          {#if data.groupChat.permissions?.includes("publish")}
            <Settings.Row
              title={m.status()}
              description={m.publishing_group_chat_description()}
            >
              <PublishingSetting
                endpoints={data.intric.groupChats}
                resource={data.groupChat}
                hasUnsavedChanges={$currentChanges.hasUnsavedChanges}
              />
            </Settings.Row>
          {/if}

          {#if data.groupChat.permissions?.includes("insight_toggle")}
            <Settings.Row
              hasChanges={$currentChanges.diff.insight_enabled !== undefined}
              revertFn={() => {
                discardChanges("insight_enabled");
              }}
              title={m.insights()}
              description={m.collect_insights_about_group_chat_usage()}
            >
              <div class="border-default flex h-14 border-b py-2">
                <Input.RadioSwitch
                  bind:value={$update.insight_enabled}
                  labelTrue={m.enable_insights()}
                  labelFalse={m.disable_insights()}
                ></Input.RadioSwitch>
              </div>
            </Settings.Row>
          {/if}
        </Settings.Group>
      {/if}

      <div class="min-h-24"></div>
    </Settings.Page>
  </Page.Main>
</Page.Root>
