<script lang="ts">
  import { goto } from "$app/navigation";
  import type { Settings } from "@eneo/eneo-js";
  import { untrack, type Snippet } from "svelte";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getTemplateController } from "$lib/features/templates/TemplateController";
  import TemplateSelector from "./TemplateSelector.svelte";
  import TemplateWizard from "./wizard/TemplateWizard.svelte";
  import CreateAppBackdrop from "./apps/CreateAppBackdrop.svelte";
  import CreateAssistantBackdrop from "./assistants/CreateAssistantBackdrop.svelte";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    kind: "app" | "assistant";
    settings: Settings;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    triggerSnippet?: Snippet<[any]>;
  };

  let { kind, settings, triggerSnippet }: Props = $props();
  const uid = $props.id();

  const kinds = {
    app: {
      title: m.create_app,
      openEditorLabel: m.open_app_editor_after_creation,
      openEditorByDefault: false,
      editPath: "apps",
      Backdrop: CreateAppBackdrop
    },
    assistant: {
      title: m.create_assistant,
      openEditorLabel: m.open_assistant_editor_after_creation,
      openEditorByDefault: true,
      editPath: "assistants",
      Backdrop: CreateAssistantBackdrop
    }
  };
  const config = $derived(kinds[kind]);

  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  const {
    state: { currentStep, createButtonLabel, creationMode, showCreateDialog },
    createOrContinue,
    resetForm
  } = getTemplateController();

  let openEditorAfterCreation = $state(untrack(() => kinds[kind].openEditorByDefault));
  let userTouchedToggle = $state(false);

  // Apps cannot run without both model types, so creating one is blocked until the space has them.
  const missingModelWarnings = $derived.by(() => {
    if (kind !== "app") return [];
    const warnings: string[] = [];
    if ($currentSpace.completion_models.length < 1) {
      warnings.push(m.completion_models_warning_app());
    }
    if ($currentSpace.transcription_models.length < 1) {
      warnings.push(m.transcription_models_warning_app());
    }
    return warnings;
  });

  function disableEditorOnTemplate(creationMode: "blank" | "template") {
    if (userTouchedToggle) return;
    openEditorAfterCreation = creationMode === "blank";
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
        if (openEditorAfterCreation) {
          // eslint-disable-next-line svelte/no-navigation-without-resolve -- dynamic URL with space and resource ids
          goto(`/spaces/${$currentSpace.routeId}/${config.editPath}/${id}/edit?next=default`);
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
        <Button {...props}>{config.title()}</Button>
      {/if}
    {/snippet}
  </Dialog.Trigger>

  <Dialog.Content class={dialogLayout.content("dynamic")} closeLabel={m.close()}>
    <form class="contents" onsubmit={(event) => event.preventDefault()}>
      <Dialog.Title class="sr-only">{config.title()}</Dialog.Title>

      <div class={dialogLayout.body}>
        {#each missingModelWarnings as warning (warning)}
          <p
            class="label-warning border-label-default bg-label-dimmer text-label-stronger m-4 rounded-md border px-2 py-1 text-sm"
          >
            <span class="font-bold">{m.warning()}:</span>
            {warning}
          </p>
          <div class="border-dimmer border-b"></div>
        {/each}

        <div class={[dialogLayout.section, "relative mt-2 -mb-0.5 overflow-hidden"]}>
          {#if $currentStep === "wizard"}
            <TemplateWizard></TemplateWizard>
          {:else}
            <TemplateSelector {settings}></TemplateSelector>

            <div class="absolute top-0 right-0 h-52 w-72 overflow-hidden">
              <config.Backdrop />
            </div>
          {/if}
        </div>
      </div>

      <Dialog.Footer class={dialogLayout.footer}>
        <Field.Field orientation="horizontal" class="w-auto p-2">
          <Switch
            id={`${uid}-open-editor`}
            bind:checked={openEditorAfterCreation}
            onCheckedChange={() => {
              userTouchedToggle = true;
            }}
          />
          <Field.Label for={`${uid}-open-editor`}>{config.openEditorLabel()}</Field.Label>
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
        <Button onclick={create} class="w-48" disabled={missingModelWarnings.length > 0}
          >{$createButtonLabel}</Button
        >
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
