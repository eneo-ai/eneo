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
    } catch (error: unknown) {
      console.error("Error restoring template:", error);
      errorMessage =
        (error instanceof Error ? error.message : String(error)) || "Failed to restore template";
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
        <div class="border-positive-default bg-positive-default/15 rounded-lg border px-4 py-3">
          <div class="flex items-start gap-3">
            <Undo class="text-positive-default shrink-0" size={20} />
            <div class="flex flex-col gap-1">
              <div class="text-default font-semibold">{template.name}</div>
              <div class="text-dimmer text-sm">{m.template_will_be_restored()}</div>
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
      <Button variant="positive" onclick={handleRestore} disabled={isLoading}>
        {isLoading ? m.restoring() : m.restore()}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
