<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { components } from "@intric/intric-js";
  import { Button, Dialog, Input } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import { getIntric } from "$lib/core/Intric.js";
  import { invalidate } from "$app/navigation";
  import { AlertTriangle } from "lucide-svelte";
  import type { Writable } from "svelte/store";

  type AssistantTemplate = components["schemas"]["AssistantTemplateAdminPublic"];
  type AppTemplate = components["schemas"]["AppTemplateAdminPublic"];
  type Template = AssistantTemplate | AppTemplate;

  let {
    openController,
    template,
    type
  }: {
    openController: Writable<boolean>;
    template: Template;
    type: "assistant" | "app";
  } = $props();

  const intric = getIntric();

  let isLoading = $state(false);
  let errorMessage = $state("");
  let confirmationText = $state("");
  let inputElement: HTMLInputElement | undefined = $state();

  // Validate against template name (case-sensitive, whitespace-trimmed)
  let isConfirmed = $derived(confirmationText.trim() === template.name);

  // Auto-focus input when modal opens
  $effect(() => {
    const isOpen = openController && typeof openController.subscribe === 'function'
      ? $state.snapshot(openController)
      : false;

    if (isOpen && inputElement) {
      setTimeout(() => inputElement?.focus(), 100);
    }
  });

  // Reset confirmation text when modal closes
  $effect(() => {
    const isOpen = openController && typeof openController.subscribe === 'function'
      ? $state.snapshot(openController)
      : false;

    if (!isOpen) {
      confirmationText = "";
      errorMessage = "";
    }
  });

  async function handlePermanentDelete() {
    if (!isConfirmed) return;

    errorMessage = "";
    isLoading = true;

    try {
      if (type === "assistant") {
        await intric.templates.admin.permanentDeleteAssistant(template.id);
      } else {
        await intric.templates.admin.permanentDeleteApp(template.id);
      }

      await invalidate("admin:templates:load");
      openController.set(false);
    } catch (error: any) {
      console.error("Error permanently deleting template:", error);
      errorMessage = error.message || "Failed to permanently delete template";
    } finally {
      isLoading = false;
    }
  }
</script>

<Dialog.Root {openController}>
  <Dialog.Content>
    <Dialog.Title>{m.permanent_delete_template()}</Dialog.Title>
    <Dialog.Description>
      {m.permanent_delete_warning()}
    </Dialog.Description>

    <Dialog.Section>
      <div class="flex flex-col gap-6 py-4">
        <!-- Warning box with template name -->
        <div class="rounded-lg border border-negative-default bg-negative-default/15 px-4 py-3">
          <div class="flex items-start gap-3">
            <AlertTriangle class="text-negative-default shrink-0" size={20} />
            <div class="flex flex-col gap-1.5">
              <div class="font-semibold text-default">{template.name}</div>
              <div class="text-sm text-dimmer">
                {m.permanent_delete_cannot_undo()}
              </div>
            </div>
          </div>
        </div>

        <!-- Confirmation input with prominent template name display -->
        <div class="flex flex-col gap-3">
          <div class="flex flex-col gap-2">
            <label for="template-name-confirm" class="text-sm font-medium text-default">
              To confirm this action, type the template name below:
            </label>
            <code class="select-all rounded-md bg-muted px-4 py-2.5 font-mono text-base font-semibold text-default border border-default">
              {template.name}
            </code>
          </div>

          <input
            id="template-name-confirm"
            bind:this={inputElement}
            type="text"
            bind:value={confirmationText}
            placeholder={template.name}
            autocomplete="off"
            autocorrect="off"
            spellcheck={false}
            class="border-default bg-primary ring-accent-default rounded-lg border px-3 py-2.5 text-sm shadow-sm focus:outline-none focus:ring-2 hover:ring-1 hover:ring-accent-dimmer transition-shadow"
            aria-describedby="template-name-display"
          />
        </div>

        {#if errorMessage}
          <div class="rounded-lg bg-negative-default/10 px-3 py-2 text-sm text-negative-default">
            {errorMessage}
          </div>
        {/if}
      </div>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close} disabled={isLoading}>{m.cancel()}</Button>
      <Button
        variant="destructive"
        onclick={handlePermanentDelete}
        disabled={!isConfirmed || isLoading}
      >
        {isLoading ? m.deleting() : m.permanent_delete()}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
