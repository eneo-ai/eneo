<script lang="ts">
  import type { Readable } from "svelte/store";
  import { fade } from "svelte/transition";
  import { afterNavigate } from "$app/navigation";
  import { page } from "$app/state";
  import { Page } from "$lib/components/layout";
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    editor: {
      state: {
        currentChanges: Readable<{ hasUnsavedChanges: boolean }>;
        isSaving: Readable<boolean>;
      };
      saveChanges: () => Promise<boolean>;
      discardChanges: () => void;
    };
    resourceName: string;
    /** Target of the back link, and of "Done" when there is no previous page to return to. */
    backHref: string;
    beforeSave?: () => void;
    beforeDiscard?: () => void;
  };

  let { editor, resourceName, backHref, beforeSave, beforeDiscard }: Props = $props();

  const currentChanges = $derived(editor.state.currentChanges);
  const isSaving = $derived(editor.state.isSaving);

  let showSavedNotice = $state(false);
  let savedNoticeTimeout: ReturnType<typeof setTimeout> | undefined;

  async function save() {
    beforeSave?.();
    if (!(await editor.saveChanges())) return;
    showSavedNotice = true;
    clearTimeout(savedNoticeTimeout);
    savedNoticeTimeout = setTimeout(() => {
      showSavedNotice = false;
    }, 5000);
  }

  function discard() {
    beforeDiscard?.();
    editor.discardChanges();
  }

  let previousHref = $state<string | null>(null);
  afterNavigate(({ from }) => {
    if (page.url.searchParams.get("next") === "default") return;
    if (from) previousHref = from.url.toString();
  });
</script>

<Page.Header>
  <Page.Title parent={{ title: resourceName, href: backHref }} title={m.edit()}></Page.Title>

  <Page.Flex>
    {#if $currentChanges.hasUnsavedChanges}
      <Button variant="destructive" disabled={$isSaving} onclick={discard}
        >{m.discard_all_changes()}</Button
      >
      <Button
        class="bg-positive-default hover:bg-positive-stronger w-32"
        disabled={$isSaving}
        aria-busy={$isSaving}
        onclick={save}>{$isSaving ? m.saving() : m.save_changes()}</Button
      >
    {:else}
      {#if showSavedNotice}
        <p class="text-positive-stronger px-4" transition:fade>{m.all_changes_saved()}</p>
      {/if}
      <Button class="w-32" href={previousHref ?? backHref}>{m.done()}</Button>
    {/if}
  </Page.Flex>
</Page.Header>
