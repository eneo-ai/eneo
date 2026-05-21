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
  import { getIntric } from "$lib/core/Intric";

  const { data } = $props();
  const intric = getIntric();

  async function save(payload: { name: string; description: string | null; text: string }) {
    const id = $page.params.id;
    if (!id) return;
    await intric.promptLibrary.update({
      id,
      name: payload.name,
      description: payload.description,
      text: payload.text
    });
    await invalidate("admin:personal-chat");
    await goto(resolve("/admin/personal-chat/prompts"));
  }
</script>

<svelte:head>
  <title>Eneo.ai – Admin – Redigera prompt</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title="Redigera prompt"></Page.Title>
  </Page.Header>
  <Page.Main>
    <div class="p-6">
      <PromptLibraryForm
        initial={{
          name: data.entry.name,
          description: data.entry.description,
          text: data.entry.text
        }}
        submitLabel="Spara"
        onSubmit={save}
        onCancel={() => goto(resolve("/admin/personal-chat/prompts"))}
      />
    </div>
  </Page.Main>
</Page.Root>
