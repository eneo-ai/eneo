<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button, Input } from "@intric/ui";
  import { IconSparkles } from "@intric/icons/sparkles";
  import { ChevronRight } from "lucide-svelte";
  import { invalidate } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { toastError } from "$lib/core/errors";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { m } from "$lib/paraglide/messages";
  import type { Intric } from "@intric/intric-js";

  type Role = Awaited<ReturnType<Intric["helpAssistants"]["admin"]["listRoles"]>>[number];

  let { role, intric }: { role: Role; intric: Intric } = $props();

  // Optimistic switch state. Initialise from a literal (referencing `role`
  // directly here would trip svelte's state_referenced_locally), then sync from
  // the server value before first paint and on every loader refresh (after a
  // successful toggle). Mirrors the admin landing page's toggles.
  let isEnabled = $state(false);
  let isVisible = $state(false);
  $effect.pre(() => {
    isEnabled = role.is_enabled;
    isVisible = role.is_visible_to_users;
  });

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

<!-- One card = one help assistant (kind). The header names it; everything inside
     (assigned assistant, toggles, reset) belongs to that single assistant. -->
<section class="border-default bg-primary overflow-hidden rounded-xl border shadow-sm">
  <header class="border-default bg-secondary flex items-center gap-3 border-b px-5 py-4">
    <span
      class="bg-accent-dimmer text-accent-stronger flex size-9 shrink-0 items-center justify-center rounded-lg"
    >
      <IconSparkles class="!size-5" />
    </span>
    <h2 class="text-lg font-medium">{roleKindLabel(role.kind)}</h2>
    <span
      class="border-default text-secondary ml-auto rounded-full border px-2.5 py-0.5 text-xs font-medium"
    >
      {m.admin_help_assistants_kind_badge()}
    </span>
  </header>

  <!-- The assistant currently assigned to this role -->
  <div class="px-5 py-4">
    <a
      class="hover:bg-hover-dimmer -mx-2 flex w-full items-center gap-3 rounded-lg px-2 py-2 transition-colors"
      href={resolve(`/spaces/${role.org_space_id}/assistants/${role.assistant_id}/edit`)}
    >
      <span
        class="bg-accent-dimmer text-accent-stronger flex size-8 shrink-0 items-center justify-center rounded-md"
      >
        <IconSparkles class="!size-4" />
      </span>
      <span class="truncate font-medium">{displayName}</span>
      <ChevronRight class="text-secondary ml-auto size-5 shrink-0" />
    </a>
  </div>

  <div class="border-default border-t px-5 py-4">
    <Input.Switch bind:value={isEnabled} sideEffect={onToggleEnabled}>
      <span class="flex flex-col gap-0.5">
        <span class="font-medium">{m.admin_help_assistants_toggle_enabled()}</span>
        <span class="text-secondary text-sm">
          {m.admin_help_assistants_toggle_enabled_description()}
        </span>
      </span>
    </Input.Switch>
  </div>

  <div class="border-default border-t px-5 py-4">
    <Input.Switch bind:value={isVisible} sideEffect={onToggleVisible}>
      <span class="flex flex-col gap-0.5">
        <span class="font-medium">{m.admin_help_assistants_toggle_visible()}</span>
        <span class="text-secondary text-sm">
          {m.admin_help_assistants_toggle_visible_description()}
        </span>
      </span>
    </Input.Switch>
  </div>

  <div class="border-default flex flex-col gap-3 border-t px-5 py-4">
    <span class="flex flex-col gap-0.5">
      <span class="font-medium">{m.admin_help_assistants_reset_section_title()}</span>
      <span class="text-secondary text-sm">
        {m.admin_help_assistants_reset_section_description()}
      </span>
    </span>
    <div class="flex flex-wrap gap-2">
      <Button variant="outlined" onclick={resetInstructions} disabled={resetInstructions.isLoading}>
        {m.admin_help_assistants_reset_instructions_button()}
      </Button>
      <Button variant="destructive" onclick={resetToDefault} disabled={resetToDefault.isLoading}>
        {m.admin_help_assistants_reset_to_default_button()}
      </Button>
    </div>
  </div>
</section>
