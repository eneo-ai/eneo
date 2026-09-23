<script lang="ts">
  import { Page, Settings } from "$lib/components/layout";
  import EditorPageHeader from "$lib/components/settings/EditorPageHeader.svelte";
  import { guardUnsavedChanges } from "$lib/core/editing/guardUnsavedChanges";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager.js";
  import AppSettingsInput from "./AppSettingsInput.svelte";
  import { initAppEditor } from "$lib/features/apps/AppEditor";
  import AttachmentsEditor from "$lib/features/attachments/components/AttachmentsEditor.svelte";
  import SelectAIModelV2 from "$lib/features/ai-models/components/SelectAIModelV2.svelte";
  import SelectBehaviourV2 from "$lib/features/ai-models/components/SelectBehaviourV2.svelte";
  import SelectModelSpecificSettings from "$lib/features/ai-models/components/SelectModelSpecificSettings.svelte";
  import {
    filterSupportedModelKwargs,
    hasModelSpecificSettings
  } from "$lib/features/ai-models/ModelKwargCapabilities";
  import PromptVersionDialog from "$lib/features/prompts/components/PromptVersionDialog.svelte";
  import dayjs from "dayjs";
  import PublishingSetting from "$lib/features/publishing/components/PublishingSetting.svelte";
  import { m } from "$lib/paraglide/messages";
  import RetentionPolicyInput from "$lib/components/settings/RetentionPolicyInput.svelte";
  import IconUpload from "$lib/features/icons/IconUpload.svelte";
  import { createIconEditor } from "$lib/features/icons/createIconEditor.svelte";
  import ApiKeysSettingsSection from "$lib/features/api-keys/ApiKeysSettingsSection.svelte";
  import SkillBindingsEditor from "$lib/features/skills/SkillBindingsEditor.svelte";
  import {
    loadSkillBindingCatalogPage,
    loadSkillBindingPreview
  } from "$lib/features/skills/skillBindingCatalog";
  import type { SkillFormValue } from "$lib/features/skills/skillBindings";
  import { untrack } from "svelte";

  let { data } = $props();
  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  const editor = untrack(() =>
    initAppEditor({
      app: data.app,
      skillBindings: data.skillBindings.map((binding) => ({
        skill_id: binding.skill_id,
        skill_revision_id: binding.skill_revision_id
      })),
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

  let cancelUploadsAndClearQueue = $state<() => void>(() => {});

  async function createSkill(value: SkillFormValue) {
    return data.eneo.skills.create({ spaceId: $currentSpace.id, ...value });
  }

  let hasBehaviorChanges = $derived.by(() => {
    if (!$currentChanges.diff.completion_model_kwargs) return false;

    if (hasModelSpecificSettings($update.completion_model)) {
      const original = $resource.completion_model_kwargs || {};
      const updated = $update.completion_model_kwargs || {};

      return original.temperature !== updated.temperature;
    }

    return true;
  });

  let iconId = $state<string | null>($resource.icon_id ?? null);
  const icon = createIconEditor({
    iconId: () => iconId,
    async setIconId(id) {
      await data.eneo.apps.update({ app: { id: $resource.id }, update: { icon_id: id } });
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
    backHref={`/spaces/${$currentSpace.routeId}/apps/${data.app.id}`}
    beforeDiscard={cancelUploadsAndClearQueue}
    beforeSave={() => {
      cancelUploadsAndClearQueue();
      $update.completion_model_kwargs = filterSupportedModelKwargs(
        $update.completion_model_kwargs,
        $update.completion_model
      );
    }}
  />

  <Page.Main>
    <Settings.Page>
      <Settings.Group title={m.general()}>
        <Settings.Row
          title={m.name()}
          description={m.app_name_description()}
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
            class="border-stronger bg-primary text-primary ring-default rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
          />
        </Settings.Row>

        <Settings.Row
          title={m.description()}
          description={m.app_description_description()}
          hasChanges={$currentChanges.diff.description !== undefined}
          revertFn={() => {
            discardChanges("description");
          }}
          let:aria
        >
          <textarea
            {...aria}
            bind:value={$update.description}
            class=" border-stronger bg-primary text-primary ring-default min-h-24 rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
          ></textarea>
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

        {#if data.app.permissions?.includes("publish")}
          <Settings.Row title={m.status()} description={m.publishing_description()}>
            <PublishingSetting
              endpoints={data.eneo.apps}
              resource={data.app}
              hasUnsavedChanges={$currentChanges.hasUnsavedChanges}
            />
          </Settings.Row>
        {/if}
      </Settings.Group>

      <Settings.Group title={m.input()}>
        <AppSettingsInput></AppSettingsInput>
      </Settings.Group>

      <Settings.Group title={m.instructions()}>
        <Settings.Row
          title={m.prompt()}
          description={m.app_prompt_description()}
          hasChanges={$currentChanges.diff.prompt !== undefined}
          revertFn={() => {
            discardChanges("prompt");
          }}
          fullWidth
          let:aria
        >
          <div slot="toolbar" class="text-secondary">
            <PromptVersionDialog
              title={m.prompt_history_for({ name: $resource.name })}
              loadPromptVersionHistory={() => {
                return data.eneo.apps.listPrompts({ id: data.app.id });
              }}
              onPromptSelected={(prompt) => {
                const restoredDate = dayjs(prompt.created_at).format("YYYY-MM-DD HH:mm");
                $update.prompt.text = prompt.text;
                $update.prompt.description = `Restored prompt from ${restoredDate}`;
              }}
            ></PromptVersionDialog>
          </div>
          <textarea
            rows={4}
            {...aria}
            bind:value={$update.prompt.text}
            onchange={() => {
              $update.prompt.description = "";
            }}
            class="border-stronger bg-primary text-primary ring-default min-h-24 rounded-lg border px-6 py-4 text-lg shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
          ></textarea>
        </Settings.Row>

        {#if $currentSpace.hasPermission("read", "skill")}
          <div id="skills" class="scroll-mt-20">
            <Settings.Row
              title={m.skills()}
              description={m.skills_editor_description()}
              hasChanges={$currentChanges.diff.skill_bindings !== undefined}
              revertFn={() => discardChanges("skill_bindings")}
            >
              <SkillBindingsEditor
                bind:bindings={$update.skill_bindings}
                initialCatalogPage={data.skills}
                bindingSummaries={data.skillBindings}
                canEditBindings={data.app.permissions?.includes("edit") ?? false}
                canCreateSkills={$currentSpace.organization !== true &&
                  $currentSpace.hasPermission("create", "skill")}
                onListCatalog={(params) =>
                  loadSkillBindingCatalogPage({
                    eneo: data.eneo,
                    spaceId: data.currentSpace.id,
                    organizationSpace: data.currentSpace.organization === true,
                    ...params
                  })}
                onGetSkillPreview={(target) =>
                  loadSkillBindingPreview({
                    eneo: data.eneo,
                    spaceId: data.currentSpace.id,
                    target
                  })}
                onCreateSkill={createSkill}
              />
            </Settings.Row>
          </div>
        {/if}

        <Settings.Row
          title={m.attachments()}
          description={m.app_attachments_description()}
          hasChanges={$currentChanges.diff.attachments !== undefined}
          revertFn={() => {
            cancelUploadsAndClearQueue();
            discardChanges("attachments");
          }}
        >
          <AttachmentsEditor
            bind:attachments={$update.attachments}
            allowedAttachments={$update.allowed_attachments}
            bind:cancelUploadsAndClearQueue
          />
        </Settings.Row>
      </Settings.Group>

      <Settings.Group title={m.ai_settings()}>
        {#if $update.input_fields.some( (field) => ["audio-recorder", "audio-upload"].includes(field.type) )}
          <Settings.Row
            title={m.transcription_model()}
            description={m.transcription_model_description()}
            hasChanges={$currentChanges.diff.transcription_model !== undefined}
            revertFn={() => {
              discardChanges("transcription_model");
            }}
            let:aria
          >
            <SelectAIModelV2
              bind:selectedModel={$update.transcription_model}
              availableModels={$currentSpace.transcription_models}
              {aria}
            ></SelectAIModelV2>
          </Settings.Row>
        {/if}

        <Settings.Row
          title={m.completion_model()}
          description={m.completion_model_description()}
          hasChanges={$currentChanges.diff.completion_model !== undefined}
          revertFn={() => {
            discardChanges("completion_model");
          }}
          let:aria
        >
          <SelectAIModelV2
            bind:selectedModel={$update.completion_model}
            availableModels={$currentSpace.completion_models}
            {aria}
          ></SelectAIModelV2>
        </Settings.Row>

        <Settings.Row
          title={m.model_behaviour()}
          description={m.model_behaviour_description()}
          hasChanges={hasBehaviorChanges}
          revertFn={() => {
            discardChanges("completion_model_kwargs");
          }}
          let:aria
        >
          <SelectBehaviourV2
            bind:kwArgs={$update.completion_model_kwargs}
            selectedModel={$update.completion_model}
            isDisabled={!$update.completion_model}
            {aria}
          ></SelectBehaviourV2>
        </Settings.Row>

        {#if hasModelSpecificSettings($update.completion_model)}
          <Settings.Row
            title={m.model_settings()}
            description={m.model_settings_description()}
            hasChanges={$currentChanges.diff.completion_model_kwargs !== undefined}
            revertFn={() => {
              discardChanges("completion_model_kwargs");
            }}
          >
            <SelectModelSpecificSettings
              bind:kwArgs={$update.completion_model_kwargs}
              selectedModel={$update.completion_model}
            ></SelectModelSpecificSettings>
          </Settings.Row>
        {/if}
      </Settings.Group>

      <Settings.Group title={m.security_and_privacy()}>
        <Settings.Row
          hasChanges={$currentChanges.diff.data_retention_days !== undefined}
          revertFn={() => {
            discardChanges("data_retention_days");
          }}
          title={m.conversation_retention_title()}
          description={m.conversation_retention_app_description()}
          let:labelId
          let:descriptionId
        >
          <RetentionPolicyInput
            bind:value={$update.data_retention_days}
            hasChanges={$currentChanges.diff.data_retention_days !== undefined}
            inheritedDays={$currentSpace.data_retention_days}
            inheritedFrom="space"
            {labelId}
            {descriptionId}
          />
        </Settings.Row>
      </Settings.Group>
      {#if data.app.permissions?.includes("edit")}
        <Settings.Group title={m.api_access()}>
          <Settings.Row title={m.api_keys()} description={m.api_keys_app_settings_desc()} fullWidth>
            <ApiKeysSettingsSection
              scopeType="app"
              scopeId={data.app.id}
              scopeName={$resource.name}
            />
          </Settings.Row>
        </Settings.Group>
      {/if}
    </Settings.Page>
  </Page.Main>
</Page.Root>
