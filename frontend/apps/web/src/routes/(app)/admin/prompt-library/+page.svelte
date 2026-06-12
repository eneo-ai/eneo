<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { invalidate, goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { Page } from "$lib/components/layout";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { m } from "$lib/paraglide/messages";
  import { Plus, Trash2, Search } from "lucide-svelte";

  const { data } = $props();

  let query = $state("");
  let confirmDelete = $state<{ id: string; name: string } | null>(null);
  let deleteError = $state<string | null>(null);
  let isDeleting = $state(false);

  const filtered = $derived(
    data.entries.items.filter((entry) => {
      const q = query.trim().toLowerCase();
      if (!q) return true;
      return (
        entry.name.toLowerCase().includes(q) || (entry.description ?? "").toLowerCase().includes(q)
      );
    })
  );

  function fmtDate(s: string) {
    return new Date(s).toLocaleString("sv-SE", { dateStyle: "short", timeStyle: "short" });
  }

  async function performDelete() {
    if (!confirmDelete) return;
    isDeleting = true;
    deleteError = null;
    try {
      await data.intric.promptLibrary.delete({ id: confirmDelete.id });
      confirmDelete = null;
      await invalidate("admin:prompt-library");
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

<Page.Root>
  <Page.Header>
    <Page.Title title={m.governance_tab_prompts()}></Page.Title>
    <Button onclick={() => goto(resolve("/admin/prompt-library/new"))} size="sm">
      <Plus class="mr-2 h-4 w-4" />
      {m.governance_prompts_create()}
    </Button>
  </Page.Header>
  <Page.Main>
    <div class="mx-auto w-full max-w-[1100px] px-6 py-6">
      <p class="text-secondary mb-6 max-w-2xl text-sm">
        {m.governance_prompts_intro()}
      </p>

      {#if data.entries.items.length === 0}
        <div
          class="border-default bg-secondary/30 flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-8 py-16"
        >
          <h2 class="text-default mb-2 text-lg font-medium">
            {m.governance_prompts_empty_title()}
          </h2>
          <p class="text-muted mb-6 max-w-sm text-center text-sm">
            {m.governance_prompts_empty_desc()}
          </p>
          <Button onclick={() => goto(resolve("/admin/prompt-library/new"))} size="sm">
            <Plus class="mr-2 h-4 w-4" />
            {m.governance_prompts_create_first()}
          </Button>
        </div>
      {:else}
        <div class="mb-3 max-w-xs">
          <div class="relative">
            <Search
              class="text-muted pointer-events-none absolute top-1/2 left-2.5 h-4 w-4 -translate-y-1/2"
              aria-hidden="true"
            />
            <Input
              bind:value={query}
              type="search"
              class="pl-8"
              placeholder={m.governance_prompts_search_placeholder()}
              aria-label={m.governance_prompts_search_placeholder()}
            />
          </div>
        </div>

        {#if filtered.length === 0}
          <p class="text-muted py-12 text-center text-sm">
            {m.governance_prompts_no_results()}
          </p>
        {:else}
          <Card.Root>
            <Table.Root>
              <Table.Header>
                <Table.Row>
                  <Table.Head>{m.name()}</Table.Head>
                  <Table.Head>{m.description()}</Table.Head>
                  <Table.Head>{m.governance_prompts_version()}</Table.Head>
                  <Table.Head>{m.governance_col_updated()}</Table.Head>
                  <Table.Head class="w-16 text-right">{m.actions()}</Table.Head>
                </Table.Row>
              </Table.Header>
              <Table.Body>
                {#each filtered as entry (entry.id)}
                  <Table.Row>
                    <Table.Cell class="font-medium">
                      <a
                        href={resolve(`/admin/prompt-library/${entry.id}`)}
                        class="text-primary hover:text-accent-default focus-visible:ring-ring rounded-sm hover:underline focus-visible:ring-2 focus-visible:outline-none"
                      >
                        {entry.name}
                      </a>
                    </Table.Cell>
                    <Table.Cell class="text-muted max-w-md truncate">
                      {entry.description ?? "—"}
                    </Table.Cell>
                    <Table.Cell class="text-muted text-sm">
                      {m.governance_prompt_version_short({ version: entry.current_version })}
                    </Table.Cell>
                    <Table.Cell class="text-muted text-sm">
                      {fmtDate(entry.updated_at)}
                    </Table.Cell>
                    <Table.Cell class="text-right">
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        title={m.delete()}
                        aria-label={m.governance_prompts_delete_label({ name: entry.name })}
                        onclick={() => (confirmDelete = { id: entry.id, name: entry.name })}
                      >
                        <Trash2 class="h-4 w-4" />
                      </Button>
                    </Table.Cell>
                  </Table.Row>
                {/each}
              </Table.Body>
            </Table.Root>
          </Card.Root>
        {/if}
      {/if}
    </div>
  </Page.Main>
</Page.Root>

<Dialog.Root
  open={confirmDelete !== null}
  onOpenChange={(o) => {
    if (!o) {
      confirmDelete = null;
      deleteError = null;
    }
  }}
>
  <Dialog.Content>
    <Dialog.Header>
      <Dialog.Title>{m.governance_prompts_delete_title()}</Dialog.Title>
      <Dialog.Description>
        {m.governance_prompts_delete_named({ name: confirmDelete?.name ?? "" })}
      </Dialog.Description>
    </Dialog.Header>
    {#if deleteError}
      <p class="text-destructive text-sm">{deleteError}</p>
    {/if}
    <Dialog.Footer>
      <Button variant="outline" onclick={() => (confirmDelete = null)} disabled={isDeleting}>
        {m.cancel()}
      </Button>
      <Button variant="destructive" onclick={performDelete} disabled={isDeleting}>
        {isDeleting ? m.governance_deleting() : m.delete()}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
