<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Page, Settings } from "$lib/components/layout";
  import { Button } from "@intric/ui";
  import { invalidate } from "$app/navigation";
  import { toastError } from "$lib/core/errors";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { m } from "$lib/paraglide/messages";
  import dayjs from "dayjs";
  import RoleRow from "./RoleRow.svelte";

  let { data } = $props();

  function historyReasonLabel(reason: string): string {
    switch (reason) {
      case "reassigned":
        return m.admin_help_assistants_history_reason_reassigned();
      case "unassigned":
        return m.admin_help_assistants_history_reason_unassigned();
      case "reset_instructions_only":
        return m.admin_help_assistants_history_reason_reset_instructions_only();
      case "reset_to_default":
        return m.admin_help_assistants_history_reason_reset_to_default();
      case "archived":
        return m.admin_help_assistants_history_reason_archived();
      default:
        return reason;
    }
  }

  // History rows only carry an actor id, not a name; show a localized generic
  // (the precise actor lives in the audit log this feature writes).
  function historyActor(actorUserId: string | null): string {
    return actorUserId
      ? m.admin_help_assistants_history_actor_admin()
      : m.admin_help_assistants_history_actor_system();
  }

  const archive = createAsyncState(async (assistantId: string, name: string) => {
    if (!confirm(m.admin_help_assistants_archive_confirm({ name }))) return;
    try {
      await data.intric.helpAssistants.admin.archive({
        kind: "prompt_guide",
        assistant_id: assistantId
      });
      await invalidate("admin:help-assistants:load");
    } catch (e) {
      toastError(e);
    }
  });
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.admin_help_assistants_page_title()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.admin_help_assistants_page_title()}></Page.Title>
  </Page.Header>
  <Page.Main>
    <Settings.Page>
      <p class="text-secondary max-w-3xl px-4 pt-4">{m.admin_help_assistants_page_intro()}</p>

      <Settings.Group title={m.admin_help_assistants_page_title()}>
        {#if data.roles.length === 0}
          <p class="text-secondary py-4">{m.admin_help_assistants_roles_empty()}</p>
        {:else}
          {#each data.roles as role (role.kind)}
            <RoleRow {role} intric={data.intric}></RoleRow>
          {/each}
        {/if}
      </Settings.Group>

      <Settings.Group title={m.admin_help_assistants_archive_section_title()}>
        {#if data.archivable.length === 0}
          <p class="text-secondary py-4">{m.admin_help_assistants_archive_empty()}</p>
        {:else}
          {#each data.archivable as item (item.id)}
            <div class="border-default flex items-center justify-between gap-4 border-b py-3">
              <span>{item.name}</span>
              <Button
                variant="destructive"
                disabled={archive.isLoading}
                onclick={() => archive(item.id, item.name)}
                >{m.admin_help_assistants_archive_button()}</Button
              >
            </div>
          {/each}
        {/if}
      </Settings.Group>

      <Settings.Group title={m.admin_help_assistants_history_section_title()}>
        {#if data.history.length === 0}
          <p class="text-secondary py-4">{m.admin_help_assistants_history_empty()}</p>
        {:else}
          <ul class="flex flex-col gap-2 py-2">
            {#each data.history as entry (entry.id)}
              <li class="text-secondary text-sm">
                {m.admin_help_assistants_history_entry_summary({
                  date: dayjs(entry.replaced_at).format("YYYY-MM-DD HH:mm"),
                  actor: historyActor(entry.actor_user_id),
                  name: entry.assistant_name_snapshot,
                  reason: historyReasonLabel(entry.reason)
                })}
              </li>
            {/each}
          </ul>
        {/if}
      </Settings.Group>
    </Settings.Page>
  </Page.Main>
</Page.Root>
