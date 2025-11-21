<script lang="ts">
  import { Page, Settings } from "$lib/components/layout";
  import { Button, Input, Tooltip } from "@intric/ui";
  import { goto } from "$app/navigation";
  import { m } from "$lib/paraglide/messages";
  import SelectAIModelV2 from "$lib/features/ai-models/components/SelectAIModelV2.svelte";
  import SelectBehaviourV2 from "$lib/features/ai-models/components/SelectBehaviourV2.svelte";
  import SelectModelSpecificSettings from "$lib/features/ai-models/components/SelectModelSpecificSettings.svelte";
  import ImprovedCategorySelector from "$lib/features/templates/components/admin/ImprovedCategorySelector.svelte";
  import LucideIconPicker from "$lib/features/templates/components/LucideIconPicker.svelte";
  import { supportsTemperature } from "$lib/features/ai-models/supportsTemperature.js";

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

    isSaving = true;
    try {
      // Transform wizard configuration to backend format
      // IMPORTANT: Always send wizard object with both properties (backend requires non-null wizard)
      const wizard = {
        attachments: wizardAttachmentsEnabled ? {
          required: wizardAttachmentsRequired,
          title: wizardAttachmentsTitle || undefined,
          description: wizardAttachmentsDescription || undefined
        } : null,
        collections: wizardCollectionsEnabled ? {
          required: wizardCollectionsRequired,
          title: wizardCollectionsTitle || undefined,
          description: wizardCollectionsDescription || undefined
        } : null
      };

      const templateData = {
        name,
        description,
        category,
        prompt: promptText,  // Backend expects string, not object
        completion_model_kwargs: completionModelKwargs,
        wizard,  // Always send wizard object, never undefined
        icon_name: iconName || undefined  // Include icon if selected
      };

      await intric.templates.admin.createAssistant(templateData);
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
  <title>Eneo.ai – {m.admin()} – {m.create_assistant_template()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title
      title={m.create_assistant_template()}
      parent={{ href: "/admin/templates", label: m.templates() }}
    />

    <Page.Flex>
      <Button variant="outlined" href="/admin/templates">{m.cancel()}</Button>
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
          description={m.assistant_name_description()}
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
          description={m.assistant_description_description()}
          hasChanges={false}
          let:aria
        >
          <textarea
            placeholder={m.assistant_placeholder({ name: name || "Assistant" })}
            {...aria}
            bind:value={description}
            class="border-default bg-primary ring-default placeholder:text-muted min-h-24 rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
          ></textarea>
        </Settings.Row>

        <Settings.Row
          title={m.category()}
          description={m.category_help()}
          hasChanges={false}
          fullWidth
        >
          <ImprovedCategorySelector bind:value={category} type="assistant" />
        </Settings.Row>
      </Settings.Group>

      <Settings.Group title={m.instructions()}>
        <Settings.Row
          title={m.prompt()}
          description={m.describe_assistant_behavior()}
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
          description={m.this_model_will_be_used()}
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
          description={m.select_preset_behavior()}
          hasChanges={false}
          let:aria
        >
          <SelectBehaviourV2
            bind:kwArgs={completionModelKwargs}
            selectedModel={completionModel}
            isDisabled={!supportsTemperature(completionModel?.name)}
            {aria}
          />
        </Settings.Row>

        {#if completionModel?.reasoning || completionModel?.litellm_model_name}
          <Settings.Row
            title="Model settings"
            description="Configure model-specific parameters for advanced control over the response."
            hasChanges={false}
          >
            <SelectModelSpecificSettings
              bind:kwArgs={completionModelKwargs}
              selectedModel={completionModel}
            />
          </Settings.Row>
        {/if}
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
