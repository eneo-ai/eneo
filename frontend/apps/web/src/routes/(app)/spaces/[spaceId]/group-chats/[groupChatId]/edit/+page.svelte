<script lang="ts">
  import { Page, Settings } from "$lib/components/layout";
  import EditorPageHeader from "$lib/components/settings/EditorPageHeader.svelte";
  import { guardUnsavedChanges } from "$lib/core/editing/guardUnsavedChanges";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager.js";
  import { useId } from "bits-ui";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as RadioGroup from "$lib/components/ui/radio-group/index.js";
  import { initGroupChatEditor } from "$lib/features/group-chats/GroupChatEditor.js";
  import GroupChatAssistantList from "$lib/features/group-chats/components/GroupChatAssistantList.svelte";
  import PublishingSetting from "$lib/features/publishing/components/PublishingSetting.svelte";
  import { getChatQueryParams } from "$lib/features/chat/getChatQueryParams.js";
  import { m } from "$lib/paraglide/messages";
  import IconUpload from "$lib/features/icons/IconUpload.svelte";
  import { createIconEditor } from "$lib/features/icons/createIconEditor.svelte";
  import { untrack } from "svelte";

  let { data } = $props();

  const mentionsId = useId();
  const responseLabelsId = useId();
  const insightsId = useId();

  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  const editor = untrack(() =>
    initGroupChatEditor({
      groupChat: data.groupChat,
      eneo: data.eneo,
      onUpdateDone() {
        refreshCurrentSpace("applications");
      }
    })
  );
  const {
    state: { resource, update, currentChanges },
    discardChanges
  } = editor;
  guardUnsavedChanges(editor);

  let iconId = $state<string | null>($resource.icon_id ?? null);
  const icon = createIconEditor({
    iconId: () => iconId,
    async setIconId(id) {
      await data.eneo.groupChats.update({
        groupChat: { id: $resource.id },
        update: { icon_id: id }
      });
      iconId = id;
      await refreshCurrentSpace("applications");
    }
  });
</script>

<svelte:head>
  <title
    >Eneo.ai – {data.currentSpace.personal ? m.personal() : data.currentSpace.name} – {$resource.name}</title
  >
</svelte:head>

<Page.Root>
  <EditorPageHeader
    {editor}
    resourceName={$resource.name}
    backHref={`/spaces/${$currentSpace.routeId}/chat/?${getChatQueryParams({ chatPartner: data.groupChat, tab: "chat" })}`}
  />

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

        <Settings.Row title={m.avatar()} description={m.avatar_description()}>
          <IconUpload
            iconUrl={icon.url}
            uploading={icon.uploading}
            error={icon.error}
            on:upload={(event) => icon.upload(event.detail)}
            on:delete={icon.remove}
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
          let:aria
        >
          <div class="border-default flex h-14 border-b py-2">
            <RadioGroup.Root
              value={$update.allow_mentions ? "on" : "off"}
              onValueChange={(v) => ($update.allow_mentions = v === "on")}
              class="grid w-full grid-cols-2 gap-2"
              {...aria}
            >
              <Field.Label for={`${mentionsId}-on`} class="font-normal">
                <Field.Field orientation="horizontal">
                  <RadioGroup.Item value="on" id={`${mentionsId}-on`} />
                  <span>{m.enable_mentions()}</span>
                </Field.Field>
              </Field.Label>
              <Field.Label for={`${mentionsId}-off`} class="font-normal">
                <Field.Field orientation="horizontal">
                  <RadioGroup.Item value="off" id={`${mentionsId}-off`} />
                  <span>{m.disable_mentions()}</span>
                </Field.Field>
              </Field.Label>
            </RadioGroup.Root>
          </div>
        </Settings.Row>

        <Settings.Row
          title={m.response_labels()}
          description={m.show_answering_assistant_name_next_to_response()}
          hasChanges={$currentChanges.diff.show_response_label !== undefined}
          revertFn={() => {
            discardChanges("show_response_label");
          }}
          let:aria
        >
          <div class="border-default flex h-14 border-b py-2">
            <RadioGroup.Root
              value={$update.show_response_label ? "on" : "off"}
              onValueChange={(v) => ($update.show_response_label = v === "on")}
              class="grid w-full grid-cols-2 gap-2"
              {...aria}
            >
              <Field.Label for={`${responseLabelsId}-on`} class="font-normal">
                <Field.Field orientation="horizontal">
                  <RadioGroup.Item value="on" id={`${responseLabelsId}-on`} />
                  <span>{m.show_labels()}</span>
                </Field.Field>
              </Field.Label>
              <Field.Label for={`${responseLabelsId}-off`} class="font-normal">
                <Field.Field orientation="horizontal">
                  <RadioGroup.Item value="off" id={`${responseLabelsId}-off`} />
                  <span>{m.hide_labels()}</span>
                </Field.Field>
              </Field.Label>
            </RadioGroup.Root>
          </div>
        </Settings.Row>
      </Settings.Group>

      {#if data.groupChat.permissions?.some((permission) => permission === "insight_toggle" || permission === "publish")}
        <Settings.Group title={m.publishing()}>
          {#if data.groupChat.permissions?.includes("publish")}
            <Settings.Row title={m.status()} description={m.publishing_group_chat_description()}>
              <PublishingSetting
                endpoints={data.eneo.groupChats}
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
              let:aria
            >
              <div class="border-default flex h-14 border-b py-2">
                <RadioGroup.Root
                  value={$update.insight_enabled ? "on" : "off"}
                  onValueChange={(v) => ($update.insight_enabled = v === "on")}
                  class="grid w-full grid-cols-2 gap-2"
                  {...aria}
                >
                  <Field.Label for={`${insightsId}-on`} class="font-normal">
                    <Field.Field orientation="horizontal">
                      <RadioGroup.Item value="on" id={`${insightsId}-on`} />
                      <span>{m.enable_insights()}</span>
                    </Field.Field>
                  </Field.Label>
                  <Field.Label for={`${insightsId}-off`} class="font-normal">
                    <Field.Field orientation="horizontal">
                      <RadioGroup.Item value="off" id={`${insightsId}-off`} />
                      <span>{m.disable_insights()}</span>
                    </Field.Field>
                  </Field.Label>
                </RadioGroup.Root>
              </div>
            </Settings.Row>
          {/if}
        </Settings.Group>
      {/if}

      <div class="min-h-24"></div>
    </Settings.Page>
  </Page.Main>
</Page.Root>
