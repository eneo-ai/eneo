<script lang="ts">
  import { Page } from "$lib/components/layout";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import CreateService from "./CreateService.svelte";
  import ServicesTable from "./ServicesTable.svelte";
  import { m } from "$lib/paraglide/messages";

  const {
    state: { currentSpace }
  } = getSpacesManager();
</script>

<svelte:head>
  <title>{m.app_name()} – {$currentSpace.personal ? m.personal() : $currentSpace.name} – {m.services()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.services()}></Page.Title>
    {#if $currentSpace.hasPermission("create", "service")}
      <CreateService></CreateService>
    {/if}
  </Page.Header>
  <Page.Main>
    <ServicesTable services={$currentSpace.applications.services}></ServicesTable>
  </Page.Main>
</Page.Root>
