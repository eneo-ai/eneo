<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Page } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";

  // Loaded roles + assignment history. The role-assignment table that renders
  // these lands in step 031; this page is currently a shell.
  let { data } = $props();
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.admin_help_assistants_page_title()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.admin_help_assistants_page_title()}></Page.Title>
  </Page.Header>
  <Page.Main>
    <div class="flex max-w-3xl flex-col gap-4 p-4">
      <p class="text-secondary">{m.admin_help_assistants_page_intro()}</p>
      <!-- Role-assignment table + actions land in step 031. -->
    </div>
  </Page.Main>
</Page.Root>
