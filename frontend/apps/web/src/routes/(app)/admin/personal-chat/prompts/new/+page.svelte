<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { goto, invalidate } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { Page } from "$lib/components/layout";
  import PromptLibraryForm from "$lib/features/prompt-library/components/PromptLibraryForm.svelte";
  import { getIntric } from "$lib/core/Intric";

  const intric = getIntric();

  async function create(payload: { name: string; description: string | null; text: string }) {
    await intric.promptLibrary.create(payload);
    await invalidate("admin:personal-chat");
    await goto(resolve("/admin/personal-chat/prompts"));
  }
</script>

<svelte:head>
  <title>Eneo.ai – Admin – Ny prompt</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title="Ny prompt"></Page.Title>
  </Page.Header>
  <Page.Main>
    <div class="p-6">
      <PromptLibraryForm
        submitLabel="Skapa"
        onSubmit={create}
        onCancel={() => goto(resolve("/admin/personal-chat/prompts"))}
      />
    </div>
  </Page.Main>
</Page.Root>
