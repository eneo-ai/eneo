<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Page, Settings } from "$lib/components/layout";
  import { Input } from "@eneo/ui";
  import { m } from "$lib/paraglide/messages";
  import HelpAssistantRow from "./HelpAssistantRow.svelte";
  import AddHelpAssistant from "./AddHelpAssistant.svelte";

  let { data } = $props();

  // Client-side filter, mirroring the Models admin page's "Filtrera …" box.
  let filter = $state("");

  function roleKindLabel(kind: string): string {
    switch (kind) {
      case "prompt_guide":
        return m.admin_help_assistants_role_kind_prompt_guide();
      default:
        return kind;
    }
  }

  const filteredRoles = $derived(
    data.roles.filter((role) => {
      const haystack = `${role.assistant_name ?? ""} ${roleKindLabel(role.kind)}`.toLowerCase();
      return haystack.includes(filter.trim().toLowerCase());
    })
  );
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.admin_help_assistants_page_title()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.admin_help_assistants_page_title()}></Page.Title>
    <Page.Flex>
      <AddHelpAssistant templates={data.templates} eneo={data.eneo} />
    </Page.Flex>
  </Page.Header>
  <Page.Main>
    <Settings.Page>
      <div class="flex flex-col gap-4 px-4 pt-2 pb-10 lg:px-2.5">
        <p class="text-secondary max-w-3xl">{m.admin_help_assistants_page_intro()}</p>

        {#if data.roles.length === 0}
          <div
            class="border-default text-secondary rounded-xl border border-dashed px-5 py-10 text-center"
          >
            {m.admin_help_assistants_roles_empty()}
          </div>
        {:else}
          <!-- Capped width (matches the MCP / Security filter bars), not full row. -->
          <div class="flex items-center gap-4">
            <Input.Text
              bind:value={filter}
              label={m.ui_filter()}
              class="max-w-md flex-grow"
              placeholder={m.admin_help_assistants_filter_placeholder()}
              hiddenLabel={true}
              inputClass="!px-4"
            ></Input.Text>
          </div>

          {#if filteredRoles.length === 0}
            <div
              class="border-default text-secondary rounded-xl border border-dashed px-5 py-10 text-center"
            >
              {m.admin_help_assistants_filter_empty()}
            </div>
          {:else}
            <!-- One bordered container, each helper a collapsible row — mirrors
                 the grouped-table look of the Models admin page. -->
            <div class="border-default bg-primary overflow-hidden rounded-xl border shadow-sm">
              {#each filteredRoles as role (role.id)}
                <HelpAssistantRow {role} eneo={data.eneo} />
              {/each}
            </div>
          {/if}
        {/if}
      </div>
    </Settings.Page>
  </Page.Main>
</Page.Root>
