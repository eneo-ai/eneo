<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { components } from "@eneo/eneo-js";
  import { Button, Dialog } from "@eneo/ui";
  import { m } from "$lib/paraglide/messages";
  import { getEneo } from "$lib/core/Eneo.js";
  import { invalidate } from "$app/navigation";
  import { RotateCcw } from "lucide-svelte";
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

  const eneo = getEneo();

  let isLoading = $state(false);
  let errorMessage = $state("");

  async function handleRollback() {
    errorMessage = "";
    isLoading = true;

    try {
      if (type === "assistant") {
        await eneo.templates.admin.rollbackAssistant(template.id);
      } else {
        await eneo.templates.admin.rollbackApp(template.id);
      }

      await invalidate("admin:templates:load");
      openController.set(false);
    } catch (error: unknown) {
      console.error("Error rolling back template:", error);
      const err = error as { status?: number; message?: string };
      if (err.status === 400) {
        errorMessage = "No snapshot available to rollback to";
      } else {
        errorMessage = err.message || "Failed to rollback template";
      }
    } finally {
      isLoading = false;
    }
  }
</script>

<Dialog.Root {openController}>
  <Dialog.Content>
    <Dialog.Title>{m.rollback_template()}</Dialog.Title>
    <Dialog.Description>
      {m.rollback_template_confirmation()}
    </Dialog.Description>

    <Dialog.Section>
      <div class="flex flex-col gap-4">
        <div class="border-accent-default bg-accent-default/10 rounded-lg border px-4 py-3">
          <div class="flex items-start gap-3">
            <RotateCcw class="text-accent-default mt-0.5 shrink-0" size={20} />
            <div class="flex flex-col gap-2">
              <div class="text-default font-medium">{template.name}</div>
              <div class="text-dimmer text-sm">
                {m.rollback_template_description()}
              </div>
            </div>
          </div>
        </div>

        {#if errorMessage}
          <div class="bg-negative-default/10 text-negative-default rounded-lg px-3 py-2 text-sm">
            {errorMessage}
          </div>
        {/if}
      </div>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close} disabled={isLoading}>{m.cancel()}</Button>
      <Button variant="primary" onclick={handleRollback} disabled={isLoading}>
        {isLoading ? m.restoring() : m.rollback()}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
