<script lang="ts" module>
  import type { components } from "@eneo/eneo-js";

  export type AppTemplatePayload = components["schemas"]["AppTemplateAdminCreate"];
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
  import InputTypeSelect, {
    type InputType
  } from "$lib/features/apps/components/InputTypeSelect.svelte";
  import LucideIconPicker from "$lib/features/templates/components/LucideIconPicker.svelte";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import ImprovedCategorySelector from "./ImprovedCategorySelector.svelte";
  import TemplateWizardStepRow from "./TemplateWizardStepRow.svelte";
  import { findTemplateModel, readWizardSteps, toWizardPayload } from "./templateForm";

  type Props = {
    /** The template being edited; omitted when creating one. */
    initial?: components["schemas"]["AppTemplateAdminPublic"];
    completionModels: CompletionModel[];
    title: string;
    submitLabel: string;
    onSubmit: (payload: AppTemplatePayload) => Promise<void>;
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
  let inputDescription = $state(untrack(() => initial?.input_description || ""));
  let inputType = $state<InputType>(
    untrack(() => (initial?.input_type || "text-field") as InputType)
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

    if (!inputType) {
      toast.warning(m.input_type_required());
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
        input_type: inputType,
        input_description: inputDescription || undefined,
        // The backend rejects app templates whose wizard has collections.
        wizard: { attachments: toWizardPayload(wizard.attachments), collections: null },
        icon_name: iconName || undefined
      });
    } finally {
      isSaving = false;
    }
  }
</script>

<Page.Root>
  <Page.Header>
    <Page.Title {title} parent={{ href: "/admin/templates", title: m.templates() }} />

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
        <Settings.Row title={m.name()} description={m.app_name_description()} let:aria>
          <div class="flex items-center gap-3">
            <LucideIconPicker bind:value={iconName} compact />
            <Input {...aria} bind:value={name} class="h-11 flex-1" />
          </div>
        </Settings.Row>

        <Settings.Row
          title={m.description()}
          description={m.app_description_description()}
          let:aria
        >
          <Textarea {...aria} bind:value={description} class="min-h-24" />
        </Settings.Row>

        <Settings.Row title={m.category()} description={m.category_help()} fullWidth>
          <ImprovedCategorySelector bind:value={category} type="app" />
        </Settings.Row>
      </Settings.Group>

      <Settings.Group title={m.input()}>
        <Settings.Row
          title={m.input_description()}
          description={m.input_description_description()}
          let:aria
        >
          <Input {...aria} bind:value={inputDescription} />
        </Settings.Row>

        <Settings.Row title={m.input_type()} description={m.input_type_description()} let:aria>
          <InputTypeSelect bind:value={inputType} {aria} />
        </Settings.Row>
      </Settings.Group>

      <Settings.Group title={m.instructions()}>
        <Settings.Row
          title={m.prompt()}
          description={m.app_prompt_description()}
          fullWidth
          let:aria
        >
          <Textarea
            {...aria}
            rows={4}
            bind:value={promptText}
            class="min-h-24 px-6 py-4 text-lg md:text-lg"
          />
        </Settings.Row>
      </Settings.Group>

      <Settings.Group title={m.ai_settings()}>
        <Settings.Row
          title={m.completion_model()}
          description={m.completion_model_description()}
          let:aria
        >
          <SelectAIModelV2
            bind:selectedModel={completionModel}
            availableModels={completionModels}
            {aria}
          />
        </Settings.Row>

        <Settings.Row
          title={m.model_behaviour()}
          description={m.model_behaviour_description()}
          let:aria
        >
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
      </Settings.Group>

      <div class="min-h-24"></div>
    </Settings.Page>
  </Page.Main>
</Page.Root>
