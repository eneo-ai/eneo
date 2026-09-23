<script lang="ts">
  import { goto } from "$app/navigation";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import TemplateSelector from "$lib/features/templates/components/TemplateSelector.svelte";
  import TemplateWizard from "$lib/features/templates/components/wizard/TemplateWizard.svelte";
  import { getTemplateController } from "$lib/features/templates/TemplateController";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import CreateAppBackdrop from "./CreateAppBackdrop.svelte";
  import { m } from "$lib/paraglide/messages";
  import type { Settings } from "@eneo/eneo-js";
  import type { Snippet } from "svelte";

  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  const {
    state: { currentStep, createButtonLabel, creationMode, showCreateDialog },
    createOrContinue,
    resetForm
  } = getTemplateController();

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let { settings, triggerSnippet }: { settings: Settings; triggerSnippet?: Snippet<[any]> } =
    $props();
  const uid = $props.id();

  let openAppAfterCreation = $state(false);
  let userTouchedToggle = $state(false);

  // Disable creation if required models are missing
  const canCreateApp = $derived(
    $currentSpace.completion_models.length > 0 && $currentSpace.transcription_models.length > 0
  );

  function disableEditorOnTemplate(creationMode: "blank" | "template") {
    if (userTouchedToggle) return;
    openAppAfterCreation = creationMode === "blank";
  }

  $effect(() => {
    disableEditorOnTemplate($creationMode);
  });

  function create() {
    createOrContinue({
      onResourceCreated: ({ id }) => {
        refreshCurrentSpace();
        $showCreateDialog = false;
        resetForm();
        if (openAppAfterCreation) {
          // eslint-disable-next-line svelte/no-navigation-without-resolve -- dynamic URL with space and app ids
          goto(`/spaces/${$currentSpace.routeId}/apps/${id}/edit?next=default`);
        }
      }
    });
  }
</script>

<Dialog.Root
  bind:open={$showCreateDialog}
  onOpenChange={(open) => {
    if (!open) resetForm();
  }}
>
  <Dialog.Trigger>
    {#snippet child({ props })}
      {#if triggerSnippet}
        {@render triggerSnippet(props)}
      {:else}
        <Button {...props}>{m.create_app()}</Button>
      {/if}
    {/snippet}
  </Dialog.Trigger>

  <Dialog.Content class={dialogLayout.content("dynamic")} closeLabel={m.close()}>
    <form class="contents" onsubmit={(event) => event.preventDefault()}>
      <Dialog.Title class="sr-only">{m.create_app()}</Dialog.Title>

      <div class={dialogLayout.body}>
        {#if $currentSpace.completion_models.length < 1}
          <p
            class="label-warning border-label-default bg-label-dimmer text-label-stronger m-4 rounded-md border px-2 py-1 text-sm"
          >
            <span class="font-bold">{m.warning()}:</span>
            {m.completion_models_warning_app()}
          </p>
          <div class="border-dimmer border-b"></div>
        {/if}
        {#if $currentSpace.transcription_models.length < 1}
          <p
            class="label-warning border-label-default bg-label-dimmer text-label-stronger m-4 rounded-md border px-2 py-1 text-sm"
          >
            <span class="font-bold">{m.warning()}:</span>
            {m.transcription_models_warning_app()}
          </p>
          <div class="border-dimmer border-b"></div>
        {/if}

        <div class={[dialogLayout.section, "relative mt-2 -mb-0.5 overflow-hidden"]}>
          {#if $currentStep === "wizard"}
            <TemplateWizard></TemplateWizard>
          {:else}
            <TemplateSelector {settings}></TemplateSelector>

            <div class="absolute top-0 right-0 h-52 w-72 overflow-hidden">
              <CreateAppBackdrop></CreateAppBackdrop>
            </div>
          {/if}
        </div>
      </div>

      <Dialog.Footer class={dialogLayout.footer}>
        <Field.Field orientation="horizontal" class="w-auto p-2">
          <Switch
            id={`${uid}-open-editor`}
            bind:checked={openAppAfterCreation}
            onCheckedChange={() => {
              userTouchedToggle = true;
            }}
          />
          <Field.Label for={`${uid}-open-editor`}>{m.open_app_editor_after_creation()}</Field.Label>
        </Field.Field>
        <div class="flex-grow"></div>

        {#if $currentStep === "wizard"}
          <Button
            variant="ghost"
            onclick={() => {
              $currentStep = "start";
            }}>{m.back()}</Button
          >
        {:else}
          <Dialog.Close class={buttonVariants({ variant: "outline" })}>{m.cancel()}</Dialog.Close>
        {/if}
        <Button onclick={create} class="w-48" disabled={!canCreateApp}>{$createButtonLabel}</Button>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
