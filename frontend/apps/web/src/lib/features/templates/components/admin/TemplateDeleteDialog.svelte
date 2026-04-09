<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { components } from "@intric/intric-js";
  import { Button, Dialog } from "@intric/ui";
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

  async function handleDelete() {
    errorMessage = "";
    isLoading = true;

    try {
      if (type === "assistant") {
        await intric.templates.admin.deleteAssistant(template.id);
      } else {
        await intric.templates.admin.deleteApp(template.id);
      }

      await invalidate("admin:templates:load");
      openController.set(false);
    } catch (error: unknown) {
      console.error("Error deleting template:", error);
      const err = error as { status?: number; message?: string };
      if (err.status === 400 && err.message?.includes("used by")) {
        // Extract usage count from error message like "used by 3 app(s)" or "used by 1 assistant(s)"
        const match = err.message.match(/used by (\d+)/);
        const count = match ? parseInt(match[1]) : 0;
        const resource =
          type === "assistant" ? m.assistants().toLowerCase() : m.apps().toLowerCase();
        errorMessage = m.template_in_use_count({ count, resource });
      } else {
        errorMessage = err.message || "Failed to delete template";
      }
    } finally {
      isLoading = false;
    }
  }
</script>

<Dialog.Root {openController}>
  <Dialog.Content>
    <Dialog.Title>{m.delete_template()}</Dialog.Title>
    <Dialog.Description>
      {m.delete_template_confirmation()}
    </Dialog.Description>

    <Dialog.Section>
      <div class="flex flex-col gap-4">
        <div class="border-warning-default bg-warning-default/15 rounded-lg border px-4 py-3">
          <div class="flex items-start gap-3">
            <AlertTriangle class="text-warning-default shrink-0" size={20} />
            <div class="flex flex-col gap-1">
              <div class="text-default font-semibold">{template.name}</div>
              <div class="text-dimmer text-sm">{m.permanent_action()}</div>
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
      <Button variant="destructive" onclick={handleDelete} disabled={isLoading}>
        {isLoading ? m.deleting() : m.delete()}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
