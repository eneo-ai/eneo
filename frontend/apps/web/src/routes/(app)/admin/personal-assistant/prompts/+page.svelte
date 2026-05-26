<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { invalidate, goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { Settings } from "$lib/components/layout";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { m } from "$lib/paraglide/messages";
  import { Plus, Trash2, Pencil } from "lucide-svelte";

  const { data } = $props();

  let confirmDeleteId = $state<string | null>(null);
  let deleteError = $state<string | null>(null);
  let isDeleting = $state(false);

  function fmtDate(s: string) {
    return new Date(s).toLocaleString("sv-SE", { dateStyle: "short", timeStyle: "short" });
  }

  async function performDelete() {
    if (!confirmDeleteId) return;
    isDeleting = true;
    deleteError = null;
    try {
      await data.intric.promptLibrary.delete({ id: confirmDeleteId });
      confirmDeleteId = null;
      await invalidate("admin:personal-assistant");
    } catch (e) {
      const err = e as { status?: number; message?: string };
      if (err.status === 409) {
        deleteError = m.governance_prompts_delete_conflict();
      } else {
        deleteError = err.message ?? m.governance_prompts_delete_error();
      }
    } finally {
      isDeleting = false;
    }
  }
</script>

<svelte:head>
  <title>{m.governance_prompts_page_title()}</title>
</svelte:head>

<div class="flex-1 overflow-y-auto px-6 pt-6">
  <Settings.Page>
    <div class="mb-4 flex items-center justify-between gap-3">
      <p class="text-secondary max-w-2xl text-sm">
        {m.governance_prompts_intro()}
      </p>
      <Button onclick={() => goto(resolve("/admin/personal-assistant/prompts/new"))} size="sm">
        <Plus class="mr-2 h-4 w-4" />
        {m.governance_prompts_create()}
      </Button>
    </div>
    <Settings.Group title={m.governance_prompts_group_title()}>
      {#if data.entries.items.length === 0}
        <div
          class="border-default bg-secondary/30 flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-8 py-16"
        >
          <h3 class="text-default mb-2 text-lg font-medium">
            {m.governance_prompts_empty_title()}
          </h3>
          <p class="text-muted mb-6 max-w-sm text-center text-sm">
            {m.governance_prompts_empty_desc()}
          </p>
          <Button onclick={() => goto(resolve("/admin/personal-assistant/prompts/new"))} size="sm">
            <Plus class="mr-2 h-4 w-4" />
            {m.governance_prompts_create_first()}
          </Button>
        </div>
      {:else}
        <Card.Root>
          <Table.Root>
            <Table.Header>
              <Table.Row>
                <Table.Head>{m.name()}</Table.Head>
                <Table.Head>{m.description()}</Table.Head>
                <Table.Head>{m.governance_col_updated()}</Table.Head>
                <Table.Head class="w-32 text-right">{m.actions()}</Table.Head>
              </Table.Row>
            </Table.Header>
            <Table.Body>
              {#each data.entries.items as entry (entry.id)}
                <Table.Row>
                  <Table.Cell class="font-medium">{entry.name}</Table.Cell>
                  <Table.Cell class="text-muted max-w-md truncate">
                    {entry.description ?? "—"}
                  </Table.Cell>
                  <Table.Cell class="text-muted text-sm">
                    {fmtDate(entry.updated_at)}
                  </Table.Cell>
                  <Table.Cell class="text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      onclick={() => goto(resolve(`/admin/personal-assistant/prompts/${entry.id}`))}
                    >
                      <Pencil class="h-4 w-4" />
                    </Button>
                    <Button variant="ghost" size="sm" onclick={() => (confirmDeleteId = entry.id)}>
                      <Trash2 class="h-4 w-4" />
                    </Button>
                  </Table.Cell>
                </Table.Row>
              {/each}
            </Table.Body>
          </Table.Root>
        </Card.Root>
      {/if}
    </Settings.Group>
  </Settings.Page>
</div>

<Dialog.Root
  open={confirmDeleteId !== null}
  onOpenChange={(o) => {
    if (!o) {
      confirmDeleteId = null;
      deleteError = null;
    }
  }}
>
  <Dialog.Content>
    <Dialog.Header>
      <Dialog.Title>{m.governance_prompts_delete_title()}</Dialog.Title>
      <Dialog.Description>
        {m.governance_prompts_delete_desc()}
      </Dialog.Description>
    </Dialog.Header>
    {#if deleteError}
      <p class="text-destructive text-sm">{deleteError}</p>
    {/if}
    <Dialog.Footer>
      <Button variant="outline" onclick={() => (confirmDeleteId = null)} disabled={isDeleting}>
        {m.cancel()}
      </Button>
      <Button variant="destructive" onclick={performDelete} disabled={isDeleting}>
        {isDeleting ? m.governance_deleting() : m.delete()}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
