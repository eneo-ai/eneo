<script lang="ts">
  import { Button } from "@intric/ui";
  import { Page } from "$lib/components/layout";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { onMount } from "svelte";
  import { getIntricSocket } from "$lib/core/IntricSocket";
  import AppResultsTable from "./results/AppResultsTable.svelte";
  import AppRunView from "./run/AppRunView.svelte";
  import AppSwitcher from "$lib/features/apps/components/AppSwitcher.svelte";
  import type { AppRunSparse } from "@intric/intric-js";
  import { fade } from "svelte/transition";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { m } from "$lib/paraglide/messages";

  export let data;

  const {
    state: { currentSpace }
  } = getSpacesManager();

  let results: AppRunSparse[] = [];
  async function updateResultsFromPageLoad(data: { results: Promise<AppRunSparse[]> }) {
    results = await data.results;
  }
  $: updateResultsFromPageLoad(data);

  const { subscribe } = getIntricSocket();

  onMount(() => {
    return subscribe("app_run_updates", async (update) => {
      if (update.app_id === data.app.id) {
        results = await data.intric.apps.runs.list({ app: data.app });
      }
    });
  });
</script>

<svelte:head>
  <title
    >Eneo.ai – {data.currentSpace.personal ? m.personal() : data.currentSpace.name} – {data.app
      .name}</title
  >
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title truncate={true} parent={{ href: `/spaces/${$currentSpace.routeId}/apps` }}>
      <AppSwitcher currentApp={data.app}></AppSwitcher>
    </Page.Title>
    <Page.Tabbar>
      <Page.TabTrigger tab="run">{m.run()}</Page.TabTrigger>
      <Page.TabTrigger tab="results">{m.results()}</Page.TabTrigger>
    </Page.Tabbar>

    <Page.Flex>
      {#if data.app.permissions?.includes("edit")}
        <Button href="/spaces/{$currentSpace.routeId}/apps/{data.app.id}/edit">{m.edit()}</Button>
      {/if}
      <Page.TabTrigger asFragment let:trigger tab="run">
        <Button is={trigger} variant="primary" class="!line-clamp-1">{m.new_run()}</Button>
      </Page.TabTrigger>
    </Page.Flex>
  </Page.Header>

  <Page.Main>
    <Page.Tab id="run">
      <AppRunView></AppRunView>
    </Page.Tab>
    <Page.Tab id="results">
      {#await data.results}
        <!-- TODO: This has some delay on it as the underlying table is delayed in updating its rows, so we cover it up during that time. -->
        <div
          class="bg-primary absolute inset-0 z-[100] flex items-center justify-center"
          out:fade={{ delay: 250, duration: 100 }}
        >
          <IconLoadingSpinner class="animate-spin"></IconLoadingSpinner>
        </div>
      {/await}
      <AppResultsTable {results} app={data.app}></AppResultsTable>
    </Page.Tab>
  </Page.Main>
</Page.Root>
