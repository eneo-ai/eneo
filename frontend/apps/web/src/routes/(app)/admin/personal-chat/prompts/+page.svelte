<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { invalidate, goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { Page, Settings } from "$lib/components/layout";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
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
      await invalidate("admin:personal-chat");
    } catch (e) {
      const err = e as { status?: number; message?: string };
      if (err.status === 409) {
        deleteError = "Prompten är aktiv i den personliga chatt-policyn. Avaktivera den först.";
      } else {
        deleteError = err.message ?? "Kunde inte ta bort prompten.";
      }
    } finally {
      isDeleting = false;
    }
  }
</script>

<svelte:head>
  <title>Eneo.ai – Admin – Promptbibliotek</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title="Promptbibliotek"></Page.Title>
    <Button onclick={() => goto(resolve("/admin/personal-chat/prompts/new"))} size="sm">
      <Plus class="mr-2 h-4 w-4" />
      Skapa ny prompt
    </Button>
  </Page.Header>
  <Page.Main>
    <Settings.Page>
      <Settings.Group title="Promptmallar">
        {#if data.entries.items.length === 0}
          <div
            class="border-default bg-secondary/30 flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-8 py-16"
          >
            <h3 class="text-default mb-2 text-lg font-medium">Inga prompts ännu</h3>
            <p class="text-muted mb-6 max-w-sm text-center text-sm">
              Promptmallar kan senare delas till alla användares personliga chatt.
            </p>
            <Button onclick={() => goto(resolve("/admin/personal-chat/prompts/new"))} size="sm">
              <Plus class="mr-2 h-4 w-4" />
              Skapa första prompten
            </Button>
          </div>
        {:else}
          <Card.Root>
            <Table.Root>
              <Table.Header>
                <Table.Row>
                  <Table.Head>Namn</Table.Head>
                  <Table.Head>Beskrivning</Table.Head>
                  <Table.Head>Uppdaterad</Table.Head>
                  <Table.Head class="w-32 text-right">Åtgärder</Table.Head>
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
                        onclick={() =>
                          // eslint-disable-next-line svelte/no-navigation-without-resolve -- dynamic id in path
                          goto(`/admin/personal-chat/prompts/${entry.id}`)}
                      >
                        <Pencil class="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onclick={() => (confirmDeleteId = entry.id)}
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
      </Settings.Group>
    </Settings.Page>
  </Page.Main>
</Page.Root>

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
      <Dialog.Title>Ta bort prompt?</Dialog.Title>
      <Dialog.Description>
        Detta kan inte ångras. Om prompten är aktiv i en personlig chatt-policy måste den
        avaktiveras där först.
      </Dialog.Description>
    </Dialog.Header>
    {#if deleteError}
      <p class="text-destructive text-sm">{deleteError}</p>
    {/if}
    <Dialog.Footer>
      <Button variant="outline" onclick={() => (confirmDeleteId = null)} disabled={isDeleting}>
        Avbryt
      </Button>
      <Button variant="destructive" onclick={performDelete} disabled={isDeleting}>
        {isDeleting ? "Tar bort..." : "Ta bort"}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
