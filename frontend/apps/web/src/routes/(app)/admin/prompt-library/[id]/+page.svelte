<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { goto, invalidate } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { page } from "$app/stores";
  import { Page } from "$lib/components/layout";
  import PromptLibraryForm from "$lib/features/prompt-library/components/PromptLibraryForm.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import { m } from "$lib/paraglide/messages";
  import { Eye, RotateCcw } from "lucide-svelte";

  const { data } = $props();
  const eneo = getEneo();

  type Version = (typeof data.versions.items)[number];

  let viewVersion = $state<Version | null>(null);
  let restoreTarget = $state<Version | null>(null);
  let restoreError = $state<string | null>(null);
  let isRestoring = $state(false);

  async function save(payload: { name: string; description: string | null; text: string }) {
    const id = $page.params.id;
    if (!id) return;
    await eneo.promptLibrary.update({
      id,
      name: payload.name,
      description: payload.description,
      text: payload.text
    });
    await invalidate("admin:prompt-library");
    await goto(resolve("/admin/prompt-library"));
  }

  async function performRestore() {
    const id = $page.params.id;
    if (!restoreTarget || !id) return;
    isRestoring = true;
    restoreError = null;
    try {
      await eneo.promptLibrary.update({
        id,
        name: restoreTarget.name,
        description: restoreTarget.description,
        text: restoreTarget.text
      });
      restoreTarget = null;
      await invalidate("admin:prompt-library");
    } catch (e) {
      const err = e as { message?: string };
      restoreError = err.message ?? m.governance_prompt_form_save_error();
    } finally {
      isRestoring = false;
    }
  }

  function fmtDate(s: string) {
    return new Date(s).toLocaleString("sv-SE", { dateStyle: "short", timeStyle: "short" });
  }
</script>

<svelte:head>
  <title>{m.governance_prompt_edit_title()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.governance_prompt_edit_heading()}></Page.Title>
  </Page.Header>
  <Page.Main>
    <div class="p-6">
      <PromptLibraryForm
        initial={{
          name: data.entry.name,
          description: data.entry.description,
          text: data.entry.text
        }}
        submitLabel={m.save()}
        onSubmit={save}
        onCancel={() => goto(resolve("/admin/prompt-library"))}
      />

      <div class="mx-auto mt-6 max-w-3xl">
        <h2 class="text-primary mb-1 text-base font-semibold">
          {m.governance_prompt_versions_title()}
        </h2>
        <p class="text-muted mb-3 text-sm">
          {m.governance_prompt_versions_intro()}
        </p>
        <Card.Root>
          <Table.Root>
            <Table.Header>
              <Table.Row>
                <Table.Head class="w-20">{m.governance_prompts_version()}</Table.Head>
                <Table.Head>{m.name()}</Table.Head>
                <Table.Head>{m.governance_prompt_versions_characters()}</Table.Head>
                <Table.Head>{m.governance_col_updated()}</Table.Head>
                <Table.Head class="w-28 text-right">{m.actions()}</Table.Head>
              </Table.Row>
            </Table.Header>
            <Table.Body>
              {#each data.versions.items as version (version.id)}
                {@const isCurrent = version.version === data.entry.current_version}
                <Table.Row>
                  <Table.Cell class="font-medium">
                    <span class="inline-flex items-center gap-2">
                      {m.governance_prompt_version_short({ version: version.version })}
                      {#if isCurrent}
                        <span
                          class="bg-positive-dimmer text-positive-stronger rounded-full px-2 py-0.5 text-xs font-medium"
                        >
                          {m.governance_prompt_versions_current()}
                        </span>
                      {/if}
                    </span>
                  </Table.Cell>
                  <Table.Cell>{version.name}</Table.Cell>
                  <Table.Cell class="text-muted text-sm">{version.text.length}</Table.Cell>
                  <Table.Cell class="text-muted text-sm">{fmtDate(version.created_at)}</Table.Cell>
                  <Table.Cell class="text-right">
                    <div class="flex items-center justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        title={m.view()}
                        aria-label={m.governance_prompt_versions_view_label({
                          version: version.version
                        })}
                        onclick={() => (viewVersion = version)}
                      >
                        <Eye class="h-4 w-4" />
                      </Button>
                      {#if !isCurrent}
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          title={m.restore()}
                          aria-label={m.governance_prompt_versions_restore_label({
                            version: version.version
                          })}
                          onclick={() => (restoreTarget = version)}
                        >
                          <RotateCcw class="h-4 w-4" />
                        </Button>
                      {/if}
                    </div>
                  </Table.Cell>
                </Table.Row>
              {/each}
            </Table.Body>
          </Table.Root>
        </Card.Root>
      </div>
    </div>
  </Page.Main>
</Page.Root>

<Dialog.Root open={viewVersion !== null} onOpenChange={(o) => !o && (viewVersion = null)}>
  <Dialog.Content class="max-w-2xl">
    <Dialog.Header>
      <Dialog.Title>
        {m.governance_prompt_versions_view_title({ version: viewVersion?.version ?? 0 })}
      </Dialog.Title>
      {#if viewVersion?.description}
        <Dialog.Description>{viewVersion.description}</Dialog.Description>
      {/if}
    </Dialog.Header>
    <div class="space-y-1">
      <p class="text-muted text-xs font-medium">{m.name()}</p>
      <p class="text-primary text-sm">{viewVersion?.name}</p>
    </div>
    <div class="space-y-1">
      <p class="text-muted text-xs font-medium">{m.governance_prompt_form_text_label()}</p>
      <div
        class="border-default bg-secondary/30 max-h-[40vh] overflow-y-auto rounded-md border p-3 text-sm break-words whitespace-pre-wrap"
      >
        {viewVersion?.text}
      </div>
    </div>
    <Dialog.Footer>
      {#if viewVersion && viewVersion.version !== data.entry.current_version}
        <Button
          variant="outline"
          onclick={() => {
            restoreTarget = viewVersion;
            viewVersion = null;
          }}
        >
          <RotateCcw class="mr-2 h-4 w-4" />
          {m.restore()}
        </Button>
      {/if}
      <Button onclick={() => (viewVersion = null)}>{m.close()}</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root
  open={restoreTarget !== null}
  onOpenChange={(o) => {
    if (!o) {
      restoreTarget = null;
      restoreError = null;
    }
  }}
>
  <Dialog.Content>
    <Dialog.Header>
      <Dialog.Title>{m.governance_prompt_versions_restore_title()}</Dialog.Title>
      <Dialog.Description>
        {m.governance_prompt_versions_restore_desc({ version: restoreTarget?.version ?? 0 })}
      </Dialog.Description>
    </Dialog.Header>
    {#if restoreError}
      <p class="text-destructive text-sm">{restoreError}</p>
    {/if}
    <Dialog.Footer>
      <Button variant="outline" onclick={() => (restoreTarget = null)} disabled={isRestoring}>
        {m.cancel()}
      </Button>
      <Button onclick={performRestore} disabled={isRestoring}>
        {isRestoring ? m.governance_prompt_versions_restoring() : m.restore()}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
