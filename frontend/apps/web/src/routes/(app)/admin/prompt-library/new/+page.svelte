<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { goto, invalidate } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { Page } from "$lib/components/layout";
  import PromptLibraryForm from "$lib/features/prompt-library/components/PromptLibraryForm.svelte";
  import { getEneo } from "$lib/core/Eneo";
  import { m } from "$lib/paraglide/messages";

  const eneo = getEneo();

  async function create(payload: { name: string; description: string | null; text: string }) {
    await eneo.promptLibrary.create(payload);
    await invalidate("admin:prompt-library");
    await goto(resolve("/admin/prompt-library"));
  }
</script>

<svelte:head>
  <title>{m.governance_prompt_new_title()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.governance_prompt_new_heading()}></Page.Title>
  </Page.Header>
  <Page.Main>
    <div class="p-6">
      <PromptLibraryForm
        submitLabel={m.create()}
        onSubmit={create}
        onCancel={() => goto(resolve("/admin/prompt-library"))}
      />
    </div>
  </Page.Main>
</Page.Root>
