<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button, Input } from "@intric/ui";
  import { IconSparkles } from "@intric/icons/sparkles";
  import { ChevronRight } from "lucide-svelte";
  import { Settings } from "$lib/components/layout";
  import { writable } from "svelte/store";
  import { invalidate } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { toastError } from "$lib/core/errors";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { m } from "$lib/paraglide/messages";
  import type { Intric } from "@intric/intric-js";
  import ReassignDialog from "./ReassignDialog.svelte";

  type Role = Awaited<ReturnType<Intric["helpAssistants"]["admin"]["listRoles"]>>[number];

  let { role, intric }: { role: Role; intric: Intric } = $props();

  // Optimistic switch state. Initialise from a literal (referencing `role`
  // directly here would trip svelte's state_referenced_locally), then sync from
  // the server value before first paint and on every loader refresh (after a
  // successful toggle / re-assign). Mirrors the admin landing page's toggles.
  let isEnabled = $state(false);
  let isVisible = $state(false);
  $effect.pre(() => {
    isEnabled = role.is_enabled;
    isVisible = role.is_visible_to_users;
  });

  const reassignOpen = writable(false);

  function roleKindLabel(kind: string): string {
    switch (kind) {
      case "prompt_guide":
        return m.admin_help_assistants_role_kind_prompt_guide();
      default:
        return kind;
    }
  }

  const displayName = $derived(role.assistant_name ?? roleKindLabel(role.kind));

  // Input.Switch only fires sideEffect on a real user change; flip optimistically
  // (the bind already did), persist, then re-sync from the loader. Revert on error.
  async function onToggleEnabled({ current, next }: { current: boolean; next: boolean }) {
    if (current === next) return;
    try {
      await intric.helpAssistants.admin.setEnabled({ kind: role.kind, value: next });
      await invalidate("admin:help-assistants:load");
    } catch (e) {
      isEnabled = current;
      toastError(e);
    }
  }

  async function onToggleVisible({ current, next }: { current: boolean; next: boolean }) {
    if (current === next) return;
    try {
      await intric.helpAssistants.admin.setVisible({ kind: role.kind, value: next });
      await invalidate("admin:help-assistants:load");
    } catch (e) {
      isVisible = current;
      toastError(e);
    }
  }

  const resetInstructions = createAsyncState(async () => {
    if (!confirm(m.admin_help_assistants_reset_instructions_confirm({ name: displayName }))) return;
    try {
      await intric.helpAssistants.admin.resetInstructions({ kind: role.kind });
      await invalidate("admin:help-assistants:load");
    } catch (e) {
      toastError(e);
    }
  });

  const resetToDefault = createAsyncState(async () => {
    if (!confirm(m.admin_help_assistants_reset_to_default_confirm({ name: displayName }))) return;
    try {
      await intric.helpAssistants.admin.resetToDefault({ kind: role.kind });
      await invalidate("admin:help-assistants:load");
    } catch (e) {
      toastError(e);
    }
  });
</script>

<Settings.Group title={roleKindLabel(role.kind)}>
  <!-- The group title is the helper kind (e.g. "Promptguide"); the assigned
       assistant leads the group as a prominent card, so no separate row label. -->
  <div class="flex flex-col items-start gap-3 px-4">
    <a
      class="border-default bg-primary hover:bg-hover-dimmer flex w-full max-w-xl items-center gap-3 rounded-lg border px-4 py-3 transition-colors"
      href={resolve(`/spaces/${role.org_space_id}/assistants/${role.assistant_id}/edit`)}
    >
      <span
        class="bg-accent-dimmer text-accent-stronger flex size-9 shrink-0 items-center justify-center rounded-md"
      >
        <IconSparkles class="!size-5" />
      </span>
      <span class="truncate font-medium">{displayName}</span>
      <ChevronRight class="text-secondary ml-auto size-5 shrink-0" />
    </a>
    <Button variant="outlined" onclick={() => ($reassignOpen = true)}>
      {m.admin_help_assistants_reassign_button()}
    </Button>
  </div>

  <Settings.Row
    title={m.admin_help_assistants_toggle_enabled()}
    description={m.admin_help_assistants_toggle_enabled_description()}
  >
    <Input.Switch bind:value={isEnabled} sideEffect={onToggleEnabled} />
  </Settings.Row>

  <Settings.Row
    title={m.admin_help_assistants_toggle_visible()}
    description={m.admin_help_assistants_toggle_visible_description()}
  >
    <Input.Switch bind:value={isVisible} sideEffect={onToggleVisible} />
  </Settings.Row>

  <Settings.Row
    title={m.admin_help_assistants_reset_section_title()}
    description={m.admin_help_assistants_reset_section_description()}
  >
    <div class="flex flex-col items-start gap-2">
      <Button variant="outlined" onclick={resetInstructions} disabled={resetInstructions.isLoading}>
        {m.admin_help_assistants_reset_instructions_button()}
      </Button>
      <Button variant="destructive" onclick={resetToDefault} disabled={resetToDefault.isLoading}>
        {m.admin_help_assistants_reset_to_default_button()}
      </Button>
    </div>
  </Settings.Row>
</Settings.Group>

<ReassignDialog {role} {intric} openController={reassignOpen} />
