<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Page, Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import HelpAssistantRow from "./HelpAssistantRow.svelte";
  import AddHelpAssistant from "./AddHelpAssistant.svelte";

  let { data } = $props();
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.admin_help_assistants_page_title()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.admin_help_assistants_page_title()}></Page.Title>
    <Page.Flex>
      <AddHelpAssistant templates={data.templates} intric={data.intric} />
    </Page.Flex>
  </Page.Header>
  <Page.Main>
    <Settings.Page>
      <div class="flex flex-col gap-6 px-4 pt-2 pb-10 lg:px-2.5">
        <p class="text-secondary max-w-3xl">{m.admin_help_assistants_page_intro()}</p>

        {#if data.roles.length === 0}
          <div
            class="border-default text-secondary rounded-xl border border-dashed px-5 py-10 text-center"
          >
            {m.admin_help_assistants_roles_empty()}
          </div>
        {:else}
          <!-- One bordered container, each helper a collapsible row — mirrors
               the grouped-table look of the Models admin page. -->
          <div class="border-default bg-primary overflow-hidden rounded-xl border shadow-sm">
            {#each data.roles as role (role.kind)}
              <HelpAssistantRow {role} intric={data.intric} />
            {/each}
          </div>
        {/if}
      </div>
    </Settings.Page>
  </Page.Main>
</Page.Root>
