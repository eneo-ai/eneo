<script lang="ts">
  import { untrack } from "svelte";
  import { Page, Settings } from "$lib/components/layout";
  import { Button, Input } from "@intric/ui";
  import { goto } from "$app/navigation";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import SelectAIModelV2 from "$lib/features/ai-models/components/SelectAIModelV2.svelte";
  import SelectBehaviourV2 from "$lib/features/ai-models/components/SelectBehaviourV2.svelte";
  import ImprovedCategorySelector from "$lib/features/templates/components/admin/ImprovedCategorySelector.svelte";
  import LucideIconPicker from "$lib/features/templates/components/LucideIconPicker.svelte";
  import { createSelect } from "@melt-ui/svelte";
  import { IconCheck } from "@intric/icons/check";
  import { IconChevronDown } from "@intric/icons/chevron-down";
  import { IconEdit } from "@intric/icons/edit";
  import { IconFileAudio } from "@intric/icons/file-audio";
  import { IconFileImage } from "@intric/icons/file-image";
  import { IconFileText } from "@intric/icons/file-text";
  import { IconMicrophone } from "@intric/icons/microphone";

  let { data } = $props();

  const intric = data.intric;

  // Template state
  let name = $state("");
  let description = $state("");
  let category = $state("");
  let iconName = $state<string | null>(null);
  let promptText = $state("");
  let completionModel = $state(data.completionModels?.[0] || null);
  let completionModelKwargs = $state({});
  let isSaving = $state(false);

  // Input field configuration
  let inputDescription = $state("");
  let inputType = $state<"text-upload" | "text-field" | "audio-upload" | "audio-recorder" | "image-upload">("text-field");

  const inputTypes = {
    "text-upload": { icon: IconFileText, label: m.upload_text_document() },
    "text-field": { icon: IconEdit, label: m.enter_text_directly() },
    "audio-upload": { icon: IconFileAudio, label: m.upload_audio_file() },
    "audio-recorder": { icon: IconMicrophone, label: m.record_microphone_audio() },
    "image-upload": { icon: IconFileImage, label: m.upload_image_file() }
  };

  const groupedTypes = {
    text: ["text-field", "text-upload"],
    audio: ["audio-recorder", "audio-upload"],
    image: ["image-upload"]
  } as const;

  const {
    elements: { trigger, menu, option, group, groupLabel },
    states: { selected },
    helpers: { isSelected }
  } = createSelect<typeof inputType>({
    positioning: {
      placement: "bottom",
      fitViewport: true,
      sameWidth: true
    },
    defaultSelected: { value: untrack(() => inputType) },
    portal: null,
    onSelectedChange: ({ next }) => {
      if (next?.value) inputType = next.value;
      return next;
    }
  });

  // Wizard configuration
  let wizardAttachmentsEnabled = $state(false);
  let wizardAttachmentsRequired = $state(false);
  let wizardAttachmentsTitle = $state("");
  let wizardAttachmentsDescription = $state("");

  let wizardCollectionsEnabled = $state(false);
  let wizardCollectionsRequired = $state(false);
  let wizardCollectionsTitle = $state("");
  let wizardCollectionsDescription = $state("");

  async function handleCreateTemplate() {
    if (!name || !category) {
      alert(m.category_required());
      return;
    }

    if (!inputType) {
      alert(m.input_type_required());
      return;
    }

    isSaving = true;
    try {
      // Transform wizard configuration to backend format
      // IMPORTANT: Always send wizard object with both properties (backend requires non-null wizard)
      // NOTE: App templates MUST have collections: null (backend validator enforces this)
      const wizard = {
        attachments: wizardAttachmentsEnabled ? {
          required: wizardAttachmentsRequired,
          title: wizardAttachmentsTitle || undefined,
          description: wizardAttachmentsDescription || undefined
        } : null,
        collections: null  // MUST be null for app templates (backend validator)
      };

      const templateData = {
        name,
        description,
        category,
        prompt: promptText,  // Backend expects string, not object
        completion_model_kwargs: completionModelKwargs,
        input_type: inputType,  // Single string, not array
        input_description: inputDescription || undefined,
        wizard,  // Always send wizard object, never undefined
        icon_name: iconName || undefined  // Include icon if selected
      };

      await intric.templates.admin.createApp(templateData);
      goto("/admin/templates?success=template_created");
    } catch (error) {
      console.error("Failed to create template:", error);
      alert(m.failed_to_create_template());
    } finally {
      isSaving = false;
    }
  }
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.create_app_template()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title
      title={m.create_app_template()}
      parent={{ href: "/admin/templates", label: m.templates() }}
    />

    <Page.Flex>
      <Button variant="outlined" href={localizeHref("/admin/templates")}>{m.cancel()}</Button>
      <Button
        variant="positive"
        class="w-32"
        onclick={handleCreateTemplate}
        disabled={isSaving}
      >
        {isSaving ? m.loading() : m.create_template()}
      </Button>
    </Page.Flex>
  </Page.Header>

  <Page.Main>
    <Settings.Page>
      <Settings.Group title={m.general()}>
        <Settings.Row
          title={m.name()}
          description={m.app_name_description()}
          hasChanges={false}
          let:aria
        >
          <div class="flex items-center gap-3">
            <LucideIconPicker bind:value={iconName} compact />
            <input
              type="text"
              {...aria}
              bind:value={name}
              class="border-default bg-primary ring-default flex-1 rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
            />
          </div>
        </Settings.Row>

        <Settings.Row
          title={m.description()}
          description={m.app_description_description()}
          hasChanges={false}
          let:aria
        >
          <textarea
            {...aria}
            bind:value={description}
            class="border-default bg-primary ring-default min-h-24 rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
          ></textarea>
        </Settings.Row>

        <Settings.Row
          title={m.category()}
          description={m.category_help()}
          hasChanges={false}
          fullWidth
        >
          <ImprovedCategorySelector bind:value={category} type="app" />
        </Settings.Row>
      </Settings.Group>

      <Settings.Group title={m.input()}>
        <Settings.Row
          title={m.input_description()}
          description={m.input_description_description()}
          hasChanges={false}
          let:aria
        >
          <input
            type="text"
            {...aria}
            bind:value={inputDescription}
            class="border-default bg-primary ring-default rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
          />
        </Settings.Row>

        <Settings.Row
          title={m.input_type()}
          description={m.input_type_description()}
          hasChanges={false}
          let:aria
        >
          <button
            {...$trigger}
            {...aria}
            use:trigger
            type="button"
            class="border-default hover:bg-hover-dimmer flex h-16 items-center justify-between border-b px-4"
          >
            {#if $selected}
              {@const IconComponent = inputTypes[$selected.value].icon}
              <div class="flex items-center gap-3">
                <IconComponent />
                <span>{inputTypes[$selected.value].label}</span>
              </div>
            {:else}
              {m.nothing_selected()}
            {/if}
            <IconChevronDown />
          </button>

          <div
            class="border-stronger bg-primary z-20 flex flex-col overflow-y-auto rounded-lg border shadow-xl"
            {...$menu}
            use:menu
          >
            {#each Object.entries(groupedTypes) as [type, inputOptions] (type)}
              <div {...$group(type)} use:group>
                <div
                  class="bg-frosted-glass-secondary border-default flex items-center gap-3 border-b px-4 py-2 font-mono text-sm capitalize"
                  {...$groupLabel(type)}
                  use:groupLabel
                >
                  {type}
                </div>
                {#each inputOptions as inputOption (inputOption)}
                  {@const { icon: IconComponent, label } = inputTypes[inputOption]}
                  <div
                    class="border-default hover:bg-hover-default flex min-h-16 items-center justify-between border-b px-4 last-of-type:border-b-0 hover:cursor-pointer"
                    {...$option({ value: inputOption })}
                    use:option
                  >
                    <div class="flex items-center gap-3">
                      <IconComponent />
                      <span>{label}</span>
                    </div>
                    <div class="check {$isSelected(inputOption) ? 'block' : 'hidden'}">
                      <IconCheck class="text-positive-default !size-8"></IconCheck>
                    </div>
                  </div>
                {/each}
              </div>
            {/each}
          </div>
        </Settings.Row>
      </Settings.Group>

      <Settings.Group title={m.instructions()}>
        <Settings.Row
          title={m.prompt()}
          description={m.app_prompt_description()}
          hasChanges={false}
          fullWidth
          let:aria
        >
          <textarea
            rows={4}
            {...aria}
            bind:value={promptText}
            class="border-default bg-primary ring-default min-h-24 rounded-lg border px-6 py-4 text-lg shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
          ></textarea>
        </Settings.Row>
      </Settings.Group>

      <Settings.Group title={m.ai_settings()}>
        <Settings.Row
          title={m.completion_model()}
          description={m.completion_model_description()}
          hasChanges={false}
          let:aria
        >
          <SelectAIModelV2
            bind:selectedModel={completionModel}
            availableModels={data.completionModels || []}
            {aria}
          />
        </Settings.Row>

        <Settings.Row
          title={m.model_behaviour()}
          description={m.model_behaviour_description()}
          hasChanges={false}
          let:aria
        >
          <SelectBehaviourV2
            bind:kwArgs={completionModelKwargs}
            selectedModel={completionModel}
            isDisabled={false}
            {aria}
          />
        </Settings.Row>
      </Settings.Group>

      <Settings.Group title={m.wizard_configuration()}>
        <Settings.Row
          title={m.wizard_attachments_section()}
          description={m.wizard_attachments_description()}
          hasChanges={false}
          fullWidth
        >
          <div class="flex flex-col gap-4">
            <Input.RadioSwitch
              bind:value={wizardAttachmentsEnabled}
              labelTrue={m.enabled()}
              labelFalse={m.disabled()}
            />

            {#if wizardAttachmentsEnabled}
              <div class="flex flex-col gap-4 rounded-lg border border-default bg-hover-default p-4">
                <label class="flex items-center gap-2">
                  <input type="checkbox" bind:checked={wizardAttachmentsRequired} />
                  <span class="text-sm text-default">{m.wizard_attachments_required_description()}</span>
                </label>

                <Input.Text
                  bind:value={wizardAttachmentsTitle}
                  placeholder={m.wizard_attachments_title_placeholder()}
                  label={m.title()}
                />

                <div class="flex flex-col gap-1">
                  <label for="wizard-attachments-description" class="text-sm font-medium text-default">{m.description()}</label>
                  <textarea
                    id="wizard-attachments-description"
                    bind:value={wizardAttachmentsDescription}
                    placeholder={m.wizard_attachments_description_placeholder()}
                    class="border-default bg-primary ring-default min-h-20 rounded-lg border px-3 py-2 text-sm shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
                  ></textarea>
                </div>
              </div>
            {/if}
          </div>
        </Settings.Row>

        <Settings.Row
          title={m.wizard_collections_section()}
          description={m.wizard_collections_description()}
          hasChanges={false}
          fullWidth
        >
          <div class="flex flex-col gap-4">
            <Input.RadioSwitch
              bind:value={wizardCollectionsEnabled}
              labelTrue={m.enabled()}
              labelFalse={m.disabled()}
            />

            {#if wizardCollectionsEnabled}
              <div class="flex flex-col gap-4 rounded-lg border border-default bg-hover-default p-4">
                <label class="flex items-center gap-2">
                  <input type="checkbox" bind:checked={wizardCollectionsRequired} />
                  <span class="text-sm text-default">{m.wizard_collections_required_description()}</span>
                </label>

                <Input.Text
                  bind:value={wizardCollectionsTitle}
                  placeholder={m.wizard_collections_title_placeholder()}
                  label={m.title()}
                />

                <div class="flex flex-col gap-1">
                  <label for="wizard-collections-description" class="text-sm font-medium text-default">{m.description()}</label>
                  <textarea
                    id="wizard-collections-description"
                    bind:value={wizardCollectionsDescription}
                    placeholder={m.wizard_collections_description_placeholder()}
                    class="border-default bg-primary ring-default min-h-20 rounded-lg border px-3 py-2 text-sm shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
                  ></textarea>
                </div>
              </div>
            {/if}
          </div>
        </Settings.Row>
      </Settings.Group>

      <div class="min-h-24"></div>
    </Settings.Page>
  </Page.Main>
</Page.Root>

<style lang="postcss">
  @reference "@intric/ui/styles";
  div[data-highlighted] {
    @apply bg-hover-default;
  }

  div[data-disabled] {
    @apply opacity-30 hover:bg-transparent;
  }
</style>
