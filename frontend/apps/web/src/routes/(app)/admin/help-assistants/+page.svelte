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
  import RoleRow from "./RoleRow.svelte";

  let { data } = $props();

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
      <div class="flex flex-col gap-6 px-4 pt-2 pb-10 lg:px-2.5">
        <p class="text-secondary max-w-3xl">{m.admin_help_assistants_page_intro()}</p>

        {#if data.roles.length === 0}
          <p class="text-secondary">{m.admin_help_assistants_roles_empty()}</p>
        {:else}
          {#each data.roles as role (role.kind)}
            <RoleRow {role} intric={data.intric}></RoleRow>
          {/each}
        {/if}
      </div>

      <Settings.Group title={m.admin_help_assistants_archive_section_title()}>
        {#if data.archivable.length === 0}
          <p class="text-secondary px-4 py-3">{m.admin_help_assistants_archive_empty()}</p>
        {:else}
          <div class="flex flex-col px-4">
            {#each data.archivable as item (item.id)}
              <div
                class="border-default flex items-center justify-between gap-4 border-b py-3 last:border-b-0"
              >
                <span class="font-medium">{item.name}</span>
                <Button
                  variant="destructive"
                  disabled={archive.isLoading}
                  onclick={() => archive(item.id, item.name)}
                >
                  {m.admin_help_assistants_archive_button()}
                </Button>
              </div>
            {/each}
          </div>
        {/if}
      </Settings.Group>
    </Settings.Page>
  </Page.Main>
</Page.Root>
