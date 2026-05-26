<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button, Input } from "@intric/ui";
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

  // Optimistic overrides layered over the server value: a toggle sets its
  // override immediately, then clears it once the loader refresh (success) or
  // a failed mutation settles the switch back to the server truth.
  let enabledOverride = $state<boolean | null>(null);
  let visibleOverride = $state<boolean | null>(null);
  const isEnabled = $derived(enabledOverride ?? role.is_enabled);
  const isVisible = $derived(visibleOverride ?? role.is_visible_to_users);

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

  const setEnabled = createAsyncState(async (next: boolean) => {
    enabledOverride = next;
    try {
      await intric.helpAssistants.admin.setEnabled({ kind: role.kind, value: next });
      await invalidate("admin:help-assistants:load");
    } catch (e) {
      toastError(e);
    } finally {
      enabledOverride = null;
    }
  });

  const setVisible = createAsyncState(async (next: boolean) => {
    visibleOverride = next;
    try {
      await intric.helpAssistants.admin.setVisible({ kind: role.kind, value: next });
      await invalidate("admin:help-assistants:load");
    } catch (e) {
      toastError(e);
    } finally {
      visibleOverride = null;
    }
  });

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

<div class="border-default flex flex-col gap-4 border-b py-5">
  <div class="flex items-start justify-between gap-4">
    <div class="flex flex-col gap-0.5">
      <span class="text-secondary text-sm">{roleKindLabel(role.kind)}</span>
      <a
        class="text-lg font-medium hover:underline"
        href={resolve(`/spaces/${role.org_space_id}/assistants/${role.assistant_id}/edit`)}
        >{displayName}</a
      >
    </div>
    <Button variant="outlined" onclick={() => ($reassignOpen = true)}>
      {m.admin_help_assistants_reassign_button()}
    </Button>
  </div>

  <div class="flex flex-col gap-3">
    <div class="flex items-center justify-between gap-4">
      <span class="font-medium">{m.admin_help_assistants_toggle_enabled()}</span>
      <Input.RadioSwitch
        value={isEnabled}
        sideEffect={({ next }) => setEnabled(next)}
        labelTrue={m.enabled()}
        labelFalse={m.disabled()}
        disabled={setEnabled.isLoading}
      ></Input.RadioSwitch>
    </div>
    <div class="flex items-center justify-between gap-4">
      <span class="font-medium">{m.admin_help_assistants_toggle_visible()}</span>
      <Input.RadioSwitch
        value={isVisible}
        sideEffect={({ next }) => setVisible(next)}
        labelTrue={m.enabled()}
        labelFalse={m.disabled()}
        disabled={setVisible.isLoading}
      ></Input.RadioSwitch>
    </div>
  </div>

  <div class="flex flex-wrap gap-2">
    <Button variant="outlined" onclick={resetInstructions} disabled={resetInstructions.isLoading}>
      {m.admin_help_assistants_reset_instructions_button()}
    </Button>
    <Button variant="destructive" onclick={resetToDefault} disabled={resetToDefault.isLoading}>
      {m.admin_help_assistants_reset_to_default_button()}
    </Button>
  </div>
</div>

<ReassignDialog {role} {intric} openController={reassignOpen} />
