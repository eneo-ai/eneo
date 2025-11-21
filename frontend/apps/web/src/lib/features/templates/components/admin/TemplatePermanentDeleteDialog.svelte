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
    const isOpen = $openController;

    if (isOpen && inputElement) {
      setTimeout(() => inputElement?.focus(), 100);
    }
  });

  // Reset confirmation text when modal closes
  $effect(() => {
    const isOpen = $openController;

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
      <div class="flex flex-col gap-4 py-4">
        <!-- Warning box with template name -->
        <div class="rounded-lg border border-negative-default bg-negative-default/15 px-4 py-3">
          <div class="flex items-start gap-3">
            <AlertTriangle class="text-negative-default shrink-0" size={20} />
            <div class="flex flex-col gap-1.5">
              <div class="font-semibold text-default">{template.name}</div>
              <div class="text-sm text-secondary">
                {m.permanent_delete_cannot_undo()}
              </div>
            </div>
          </div>
        </div>

        <!-- Confirmation input -->
        <Input.Text
          id="template-name-confirm"
          bind:inputElement
          bind:value={confirmationText}
          placeholder={template.name}
          label={m.permanent_delete_type_to_confirm({ word: template.name })}
          autocomplete="off"
          autocorrect="off"
          spellcheck={false}
        />

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
