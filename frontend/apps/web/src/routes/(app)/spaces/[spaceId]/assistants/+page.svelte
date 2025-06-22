<script lang="ts">
  import { Page } from "$lib/components/layout";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { onMount } from "svelte";
  import AssistantsTable from "./AssistantsTable.svelte";
  import TemplateCreateAssistantHint from "$lib/features/templates/components/assistants/TemplateCreateAssistantHint.svelte";
  import { initTemplateController } from "$lib/features/templates/TemplateController";
  import { createAssistantTemplateAdapter } from "$lib/features/templates/TemplateAdapter";
  import CreateNew from "./CreateNew.svelte";
  import { m } from "$lib/paraglide/messages";

  export let data;

  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  initTemplateController({
    adapter: createAssistantTemplateAdapter({
      intric: data.intric,
      currentSpaceId: $currentSpace.id
    }),
    allTemplates: data.allTemplates
  });

  onMount(() => {
    refreshCurrentSpace();
  });
</script>

<svelte:head>
  <title>Eneo.ai – {$currentSpace.personal ? m.personal() : $currentSpace.name} – {m.assistants()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.assistants()}></Page.Title>
    <!--
      We made the decision to not look at assistants and group chats as individual permissions for now,
      meaning if we ever intend to change that, we would need that distinction here
    -->
    {#if $currentSpace.hasPermission("create", "assistant")}
      <CreateNew></CreateNew>
    {/if}
  </Page.Header>

  <Page.Main>
    {#if $currentSpace.applications.assistants.length < 1 && data.featureFlags.showTemplates && $currentSpace.hasPermission("create", "assistant")}
      <TemplateCreateAssistantHint></TemplateCreateAssistantHint>
    {:else}
      <AssistantsTable items={$currentSpace.applications.chat}></AssistantsTable>
    {/if}
  </Page.Main>
</Page.Root>
