<script lang="ts">
  import { Button } from "@intric/ui";
  import { fade, fly } from "svelte/transition";
  import { quadInOut } from "svelte/easing";
  import { onMount } from "svelte";
  import { getIntricSocket } from "$lib/core/IntricSocket";
  import { getIntric } from "$lib/core/Intric";
  import type { AppRunSparse } from "@intric/intric-js";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import DashboardAppRunView from "./DashboardAppRunView.svelte";
  import DashboardAppResultsTable from "./DashboardAppResultsTable.svelte";

  export let data;

  const intric = getIntric();

  let results: AppRunSparse[] = [];
  let activeTab: "run" | "results" = "run";

  async function updateResultsFromPageLoad(pageData: { results: Promise<AppRunSparse[]> }) {
    results = await pageData.results;
  }
  $: updateResultsFromPageLoad(data);

  const { subscribe } = getIntricSocket();

  onMount(() => {
    return subscribe("app_run_updates", async (update) => {
      if (update.app_id === data.app.id) {
        results = await intric.apps.runs.list({ app: data.app });
      }
    });
  });
</script>

<svelte:head>
  <title>Eneo.ai – Dashboard – {data.app.name}</title>
</svelte:head>

<div class="outer bg-primary flex w-full flex-col">
  <div
    class="bg-primary sticky top-0 z-10 flex items-center justify-between px-3.5 py-3 backdrop-blur-md"
    in:fade={{ duration: 50 }}
  >
    <a href={localizeHref("/dashboard")} class="flex max-w-[calc(100%_-_7rem)] flex-grow items-center rounded-lg">
      <span
        class="border-default hover:bg-hover-dimmer flex h-8 w-8 items-center justify-center rounded-lg border"
        >←</span
      >
      <h1
        in:fly|global={{
          x: -5,
          duration: 300,
          easing: quadInOut,
          opacity: 0.3
        }}
        class="truncate px-3 py-1 text-xl font-extrabold"
      >
        {data.app.name}
      </h1>
    </a>
    <Button
      variant="primary"
      on:click={() => {
        activeTab = "run";
      }}
      class="!rounded-lg !border-b-2 !border-[var(--color-ui-blue-700)] !px-5 !py-1"
      >{m.new_run()}
    </Button>
  </div>

  <div class="border-default flex border-b px-3.5">
    <button
      class="border-b-2 px-4 py-2 text-sm font-medium transition-colors"
      class:border-[var(--color-ui-blue-600)]={activeTab === "run"}
      class:text-primary={activeTab === "run"}
      class:border-transparent={activeTab !== "run"}
      class:text-secondary={activeTab !== "run"}
      on:click={() => (activeTab = "run")}
    >
      {m.run()}
    </button>
    <button
      class="border-b-2 px-4 py-2 text-sm font-medium transition-colors"
      class:border-[var(--color-ui-blue-600)]={activeTab === "results"}
      class:text-primary={activeTab === "results"}
      class:border-transparent={activeTab !== "results"}
      class:text-secondary={activeTab !== "results"}
      on:click={() => (activeTab = "results")}
    >
      {m.results()}
    </button>
  </div>

  <div class="flex-grow overflow-y-auto">
    {#if activeTab === "run"}
      <DashboardAppRunView />
    {:else}
      <div class="p-4">
        <DashboardAppResultsTable {results} app={data.app} />
      </div>
    {/if}
  </div>
</div>

<style>
  @media (display-mode: standalone) {
    .outer {
      background-color: var(--background-primary);
      overflow-y: auto;
      margin: 0 0.5rem;
      border-radius: 1rem;
      box-shadow: 0 4px 10px 0px rgba(0, 0, 0, 0.1);
      max-height: 100%;
    }
  }

  @container (min-width: 1000px) {
    .outer {
      margin: 1.5rem;
      border-radius: 1rem;
      box-shadow: 0 4px 10px 0px rgba(0, 0, 0, 0.1);
      max-width: 1400px;
      overflow: hidden;
    }
  }
</style>
