<script lang="ts">
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import TemplateSelector from "$lib/features/templates/components/TemplateSelector.svelte";
  import TemplateWizard from "$lib/features/templates/components/wizard/TemplateWizard.svelte";
  import { getTemplateController } from "$lib/features/templates/TemplateController";
  import { Button, Dialog, Input } from "@intric/ui";
  import CreateAssistantBackdrop from "./CreateAssistantBackdrop.svelte";
  import { goto } from "$app/navigation";
  import { m } from "$lib/paraglide/messages";
  import type { Settings } from "@intric/intric-js";
  import type { Snippet } from "svelte";

  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  const {
    createOrContinue,
    resetForm,
    state: { currentStep, createButtonLabel, creationMode, showCreateDialog }
  } = getTemplateController();

  let { settings, triggerSnippet }: { settings: Settings; triggerSnippet?: Snippet<[any]> } = $props();

  let openAssistantAfterCreation = $state(true);
  let userTouchedToggle = $state(false);

  function disableEditorOnTemplate(creationMode: "blank" | "template") {
    if (userTouchedToggle) return;
    openAssistantAfterCreation = creationMode === "blank";
  }

  $effect(() => {
    disableEditorOnTemplate($creationMode);
  });
</script>

<Dialog.Root openController={showCreateDialog} on:close={resetForm}>
  <Dialog.Trigger asFragment let:trigger>
    {#if triggerSnippet}
      {@render triggerSnippet(trigger)}
    {:else}
      <Button is={trigger} variant="primary">{m.create_assistant()}</Button>
    {/if}
  </Dialog.Trigger>

  <Dialog.Content width="dynamic" form>
    <Dialog.Section class="relative mt-2 -mb-0.5">
      {#if $currentStep === "wizard"}
        <TemplateWizard></TemplateWizard>
      {:else}
        <TemplateSelector {settings}></TemplateSelector>
        <div class="absolute top-0 right-0 h-52 w-72 overflow-hidden">
          <CreateAssistantBackdrop></CreateAssistantBackdrop>
        </div>
      {/if}
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Input.Switch
        bind:value={openAssistantAfterCreation}
        sideEffect={() => {
          userTouchedToggle = true;
        }}
        class="flex-row-reverse p-2">{m.open_assistant_editor_after_creation()}</Input.Switch
      >
      <div class="flex-grow"></div>

      {#if $currentStep === "wizard"}
        <Button
          on:click={() => {
            $currentStep = "start";
          }}>{m.back()}</Button
        >
      {:else}
        <Button is={close}>{m.cancel()}</Button>
      {/if}
      <Button
        variant="primary"
        class="w-40"
        on:click={() => {
          createOrContinue({
            onResourceCreated: ({ id }) => {
              refreshCurrentSpace();
              $showCreateDialog = false;
              resetForm();
              if (openAssistantAfterCreation) {
                goto(`/spaces/${$currentSpace.routeId}/assistants/${id}/edit?next=default`);
              }
            }
          });
        }}>{$createButtonLabel}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
