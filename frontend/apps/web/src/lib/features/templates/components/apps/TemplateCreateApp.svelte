<script lang="ts">
  import { goto } from "$app/navigation";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import TemplateSelector from "$lib/features/templates/components/TemplateSelector.svelte";
  import TemplateWizard from "$lib/features/templates/components/wizard/TemplateWizard.svelte";
  import { getTemplateController } from "$lib/features/templates/TemplateController";
  import { Button, Dialog, Input } from "@intric/ui";
  import CreateAppBackdrop from "./CreateAppBackdrop.svelte";
  import { m } from "$lib/paraglide/messages";

  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  const {
    state: { currentStep, createButtonLabel, creationMode, showCreateDialog },
    createOrContinue,
    resetForm
  } = getTemplateController();

  let openAppAfterCreation = false;
  let userTouchedToggle = false;

  function disableEditorOnTemplate(creationMode: "blank" | "template") {
    if (userTouchedToggle) return;
    openAppAfterCreation = creationMode === "blank";
  }

  $: disableEditorOnTemplate($creationMode);
</script>

<Dialog.Root openController={showCreateDialog} on:close={resetForm}>
  <Dialog.Trigger asFragment let:trigger>
    {#if $$slots.default}
      <slot {trigger}></slot>
    {:else}
      <Button is={trigger} variant="primary">{m.create_app()}</Button>
    {/if}
  </Dialog.Trigger>

  <Dialog.Content width="dynamic" form>
    {#if $currentSpace.completion_models.length < 1}
      <p
        class="label-warning border-label-default bg-label-dimmer text-label-stronger m-4 rounded-md border px-2 py-1 text-sm"
      >
        <span class="font-bold">{m.warning()}:</span>
        {m.completion_models_warning_app()}
      </p>
      <div class="border-dimmer border-b"></div>
    {/if}

    <Dialog.Section class="relative mt-2 -mb-0.5">
      {#if $currentStep === "wizard"}
        <TemplateWizard></TemplateWizard>
      {:else}
        <TemplateSelector></TemplateSelector>

        <div class="absolute top-0 right-0 h-52 w-72 overflow-hidden">
          <CreateAppBackdrop></CreateAppBackdrop>
        </div>
      {/if}
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Input.Switch
        bind:value={openAppAfterCreation}
        class="flex-row-reverse p-2"
        sideEffect={() => {
          userTouchedToggle = true;
        }}>{m.open_app_editor_after_creation()}</Input.Switch
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
        class="w-48"
        on:click={() => {
          createOrContinue({
            onResourceCreated({ id }) {
              refreshCurrentSpace();
              $showCreateDialog = false;
              resetForm();
              if (openAppAfterCreation) {
                goto(`/spaces/${$currentSpace.routeId}/apps/${id}/edit?next=default`);
              }
            }
          });
        }}>{$createButtonLabel}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
