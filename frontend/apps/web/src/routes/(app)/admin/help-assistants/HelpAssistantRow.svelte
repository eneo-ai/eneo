<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button, Input } from "@eneo/ui";
  import { IconSparkles } from "@eneo/icons/sparkles";
  import { IconChevronDown } from "@eneo/icons/chevron-down";
  import { invalidate } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { toastError } from "$lib/core/errors";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { m } from "$lib/paraglide/messages";
  import type { Eneo } from "@eneo/eneo-js";

  type Role = Awaited<ReturnType<Eneo["helpAssistants"]["admin"]["listRoles"]>>[number];

  let { role, eneo }: { role: Role; eneo: Eneo } = $props();

  let isOpen = $state(false);

  // Optimistic switch state. Initialise from a literal (referencing `role`
  // directly here would trip svelte's state_referenced_locally), then sync from
  // the server value before first paint and on every loader refresh.
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
  const settingsHref = $derived(resolve(`/admin/help-assistants/${role.kind}`));

  // Input.Switch only fires sideEffect on a real user change; flip optimistically
  // (the bind already did), persist, then re-sync from the loader. Revert on error.
  async function onToggleEnabled({ current, next }: { current: boolean; next: boolean }) {
    if (current === next) return;
    try {
      await eneo.helpAssistants.admin.setEnabled({ kind: role.kind, value: next });
      await invalidate("admin:help-assistants:load");
    } catch (e) {
      isEnabled = current;
      toastError(e);
    }
  }

  async function onToggleVisible({ current, next }: { current: boolean; next: boolean }) {
    if (current === next) return;
    try {
      await eneo.helpAssistants.admin.setVisible({ kind: role.kind, value: next });
      await invalidate("admin:help-assistants:load");
    } catch (e) {
      isVisible = current;
      toastError(e);
    }
  }

  const remove = createAsyncState(async () => {
    if (!confirm(m.admin_help_assistants_delete_confirm({ name: displayName }))) return;
    try {
      await eneo.helpAssistants.admin.uninstall({ kind: role.kind });
      await invalidate("admin:help-assistants:load");
    } catch (e) {
      toastError(e);
    }
  });
</script>

<div class="border-default border-b last:border-b-0">
  <!-- Collapsible header: toggling the chevron/name reveals this helper's
       settings, mirroring the grouped rows on the Models admin page. -->
  <div class="flex items-center gap-2 px-2.5 py-3.5">
    <Button onclick={() => (isOpen = !isOpen)} padding="icon-leading" aria-label={displayName}>
      <IconChevronDown class="{isOpen ? 'rotate-0' : '-rotate-90'} w-5 transition-all" />
    </Button>
    <span
      class="bg-accent-dimmer text-accent-stronger flex size-8 shrink-0 items-center justify-center rounded-md"
    >
      <IconSparkles class="!size-4" />
    </span>
    <Button onclick={() => (isOpen = !isOpen)} padding="text" class="-ml-1 font-medium">
      <span>{roleKindLabel(role.kind)}</span>
    </Button>
    <span
      class="border-default text-secondary ml-auto rounded-full border px-2.5 py-0.5 text-xs font-medium"
    >
      {m.admin_help_assistants_kind_badge()}
    </span>
  </div>

  {#if isOpen}
    <div class="border-default flex flex-col gap-4 border-t px-5 py-4">
      <Input.Switch bind:value={isEnabled} sideEffect={onToggleEnabled}>
        <span class="flex flex-col gap-0.5">
          <span class="font-medium">{m.admin_help_assistants_toggle_enabled()}</span>
          <span class="text-secondary text-sm">
            {m.admin_help_assistants_toggle_enabled_description()}
          </span>
        </span>
      </Input.Switch>

      <Input.Switch bind:value={isVisible} sideEffect={onToggleVisible}>
        <span class="flex flex-col gap-0.5">
          <span class="font-medium">{m.admin_help_assistants_toggle_visible()}</span>
          <span class="text-secondary text-sm">
            {m.admin_help_assistants_toggle_visible_description()}
          </span>
        </span>
      </Input.Switch>

      <div class="border-default flex flex-wrap items-center justify-between gap-2 border-t pt-4">
        <Button variant="primary" href={settingsHref}>
          {m.admin_help_assistants_open_settings()}
        </Button>
        <Button variant="destructive" onclick={remove} disabled={remove.isLoading}>
          {m.admin_help_assistants_delete_button()}
        </Button>
      </div>
    </div>
  {/if}
</div>
