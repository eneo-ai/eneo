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
  import { Undo } from "lucide-svelte";
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

  async function handleRestore() {
    errorMessage = "";
    isLoading = true;

    try {
      if (type === "assistant") {
        await intric.templates.admin.restoreAssistant(template.id);
      } else {
        await intric.templates.admin.restoreApp(template.id);
      }

      await invalidate("admin:templates:load");
      openController.set(false);
    } catch (error: any) {
      console.error("Error restoring template:", error);
      errorMessage = error.message || "Failed to restore template";
    } finally {
      isLoading = false;
    }
  }
</script>

<Dialog.Root {openController}>
  <Dialog.Content>
    <Dialog.Title>{m.restore_template()}</Dialog.Title>
    <Dialog.Description>
      {m.restore_template_confirmation()}
    </Dialog.Description>

    <Dialog.Section>
      <div class="flex flex-col gap-4">
        <div class="rounded-lg border border-positive-default bg-positive-default/10 px-4 py-3">
          <div class="flex items-start gap-3">
            <Undo class="text-positive-default mt-0.5 shrink-0" size={20} />
            <div class="flex flex-col gap-2">
              <div class="font-medium text-default">{template.name}</div>
              <div class="text-sm text-dimmer">{m.template_will_be_restored()}</div>
            </div>
          </div>
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
      <Button variant="positive" onclick={handleRestore} disabled={isLoading}>
        {isLoading ? m.restoring() : m.restore()}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
