<script lang="ts" module>
  import type { components } from "@eneo/eneo-js";

  export type AssistantTemplatePayload = components["schemas"]["AssistantTemplateAdminCreate"];
</script>

<script lang="ts">
  import { untrack } from "svelte";
  import type { CompletionModel, ModelKwargs } from "@eneo/eneo-js";
  import { Page, Settings } from "$lib/components/layout";
  import { toast } from "$lib/components/toast";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import SelectAIModelV2 from "$lib/features/ai-models/components/SelectAIModelV2.svelte";
  import SelectBehaviourV2 from "$lib/features/ai-models/components/SelectBehaviourV2.svelte";
  import SelectModelSpecificSettings from "$lib/features/ai-models/components/SelectModelSpecificSettings.svelte";
  import {
    filterSupportedModelKwargs,
    hasModelSpecificSettings
  } from "$lib/features/ai-models/ModelKwargCapabilities";
  import LucideIconPicker from "$lib/features/templates/components/LucideIconPicker.svelte";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import ImprovedCategorySelector from "./ImprovedCategorySelector.svelte";
  import TemplateWizardStepRow from "./TemplateWizardStepRow.svelte";
  import { findTemplateModel, readWizardSteps, toWizardPayload } from "./templateForm";

  type Props = {
    /** The template being edited; omitted when creating one. */
    initial?: components["schemas"]["AssistantTemplateAdminPublic"];
    completionModels: CompletionModel[];
    title: string;
    submitLabel: string;
    onSubmit: (payload: AssistantTemplatePayload) => Promise<void>;
  };

  let { initial, completionModels, title, submitLabel, onSubmit }: Props = $props();

  let name = $state(untrack(() => initial?.name || ""));
  let description = $state(untrack(() => initial?.description || ""));
  let category = $state(untrack(() => initial?.category || ""));
  let iconName = $state<string | null>(untrack(() => initial?.icon_name || null));
  let promptText = $state(untrack(() => initial?.prompt_text || ""));
  let completionModel = $state(untrack(() => findTemplateModel(completionModels, initial)));
  let completionModelKwargs = $state<ModelKwargs>(
    untrack(() => initial?.completion_model_kwargs || {})
  );
  let wizard = $state(untrack(() => readWizardSteps(initial)));
  let isSaving = $state(false);

  async function save() {
    if (!name.trim()) {
      toast.warning(m.template_name_required());
      return;
    }
    if (!category) {
      toast.warning(m.category_required());
      return;
    }

    isSaving = true;
    try {
      await onSubmit({
        name,
        description,
        category,
        prompt: promptText,
        completion_model_id: completionModel?.id,
        completion_model_kwargs: filterSupportedModelKwargs(completionModelKwargs, completionModel),
        // The backend rejects a null wizard, so both steps are always sent.
        wizard: {
          attachments: toWizardPayload(wizard.attachments),
          collections: toWizardPayload(wizard.collections)
        },
        icon_name: iconName || undefined
      });
    } finally {
      isSaving = false;
    }
  }
</script>

<Page.Root>
  <Page.Header>
    <Page.Title
      {title}
      parent={{ href: "/admin/templates", title: m.assistant_and_app_templates() }}
    />

    <Page.Flex>
      <Button variant="outline" href={localizeHref("/admin/templates")}>{m.cancel()}</Button>
      <Button
        class="bg-positive-default hover:bg-positive-stronger min-w-32"
        onclick={save}
        disabled={isSaving}
      >
        {isSaving ? m.loading() : submitLabel}
      </Button>
    </Page.Flex>
  </Page.Header>

  <Page.Main>
    <Settings.Page>
      <Settings.Group title={m.general()}>
        <Settings.Row title={m.name()} description={m.assistant_name_description()} let:aria>
          <div class="flex items-center gap-3">
            <LucideIconPicker bind:value={iconName} compact />
            <Input {...aria} bind:value={name} class="h-11 flex-1" />
          </div>
        </Settings.Row>

        <Settings.Row
          title={m.description()}
          description={m.assistant_description_description()}
          let:aria
        >
          <Textarea
            {...aria}
            bind:value={description}
            placeholder={m.assistant_placeholder({ name: name || m.assistant() })}
            class="min-h-24"
          />
        </Settings.Row>

        <Settings.Row title={m.category()} description={m.category_help()} fullWidth>
          <ImprovedCategorySelector bind:value={category} type="assistant" />
        </Settings.Row>
      </Settings.Group>

      <Settings.Group title={m.instructions()}>
        <Settings.Row
          title={m.prompt()}
          description={m.describe_assistant_behavior()}
          fullWidth
          let:aria
        >
          <Textarea
            {...aria}
            rows={4}
            bind:value={promptText}
            class="min-h-36 px-6 py-4 text-lg md:text-lg"
          />
        </Settings.Row>
      </Settings.Group>

      <Settings.Group title={m.ai_settings()}>
        <Settings.Row
          title={m.completion_model()}
          description={m.this_model_will_be_used()}
          let:aria
        >
          <SelectAIModelV2
            bind:selectedModel={completionModel}
            availableModels={completionModels}
            {aria}
          />
        </Settings.Row>

        <Settings.Row title={m.model_behaviour()} description={m.select_preset_behavior()} let:aria>
          <SelectBehaviourV2
            bind:kwArgs={completionModelKwargs}
            selectedModel={completionModel}
            isDisabled={!completionModel}
            {aria}
          />
        </Settings.Row>

        {#if hasModelSpecificSettings(completionModel)}
          <Settings.Row title={m.model_settings()} description={m.model_settings_description()}>
            <SelectModelSpecificSettings
              bind:kwArgs={completionModelKwargs}
              selectedModel={completionModel}
            />
          </Settings.Row>
        {/if}
      </Settings.Group>

      <Settings.Group title={m.wizard_configuration()}>
        <TemplateWizardStepRow kind="attachments" bind:step={wizard.attachments} />
        <TemplateWizardStepRow kind="collections" bind:step={wizard.collections} />
      </Settings.Group>

      <div class="min-h-24"></div>
    </Settings.Page>
  </Page.Main>
</Page.Root>
