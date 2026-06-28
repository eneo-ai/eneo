<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Page } from "$lib/components/layout";
  import { Input } from "@eneo/ui";
  import ChatView from "./ChatView.svelte";
  import { goto } from "$app/navigation";
  import { page } from "$app/stores";
  import QuestionTable from "./QuestionTable.svelte";
  import { m } from "$lib/paraglide/messages";

  export let data;

  let includeFollowups: boolean = data.includeFollowups;
  let timeframe = data.timeframe;
  let refreshToken = 0;

  let activeTab = "chat";
  $: activeTab = $page.url.searchParams.get("tab") ?? "chat";

  let prevFilterKey = `${data.timeframe.start}|${data.timeframe.end}|${data.includeFollowups}`;
  $: filterKey = `${timeframe.start}|${timeframe.end}|${includeFollowups}`;
  $: if (filterKey !== prevFilterKey) {
    prevFilterKey = filterKey;
    refreshToken += 1;
    void syncFiltersToUrl();
  }

  async function syncFiltersToUrl() {
    const nextUrl = new URL($page.url);
    nextUrl.searchParams.set("from", timeframe.start.toString());
    nextUrl.searchParams.set("to", timeframe.end.toString());
    nextUrl.searchParams.set("followups", includeFollowups ? "true" : "false");
    // eslint-disable-next-line svelte/no-navigation-without-resolve -- dynamic query string
    await goto(nextUrl.toString(), {
      replaceState: true,
      noScroll: true,
      keepFocus: true,
      invalidateAll: false
    });
  }
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {data.assistant.name} – {m.insights()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title
      parent={{ title: m.insights(), href: "/admin/insights?tab=assistants" }}
      title={data.assistant.name}
    ></Page.Title>
    <Page.Tabbar>
      <Page.TabTrigger tab="chat">{m.analyse()}</Page.TabTrigger>
      <Page.TabTrigger tab="questions">{m.question_history()}</Page.TabTrigger>
    </Page.Tabbar>
  </Page.Header>

  <div
    class="filter-bar border-default bg-primary mx-6 mt-3 mb-1 flex flex-wrap items-center justify-between gap-4 rounded-lg border px-4 py-2.5"
    style="--delay: 0ms"
  >
    <Input.DateRange bind:value={timeframe} class="border-0 p-0"
      >{m.included_timeframe()}</Input.DateRange
    >
    <Input.Switch bind:value={includeFollowups} class="border-0 p-0 text-sm"
      >{m.include_follow_up_questions()}</Input.Switch
    >
  </div>

  <Page.Main>
    <Page.Tab id="chat">
      <ChatView assistant={data.assistant} {includeFollowups} {timeframe}></ChatView>
    </Page.Tab>
    <Page.Tab id="questions">
      <QuestionTable
        assistantId={$page.params.assistantId ?? ""}
        eneo={data.eneo}
        {includeFollowups}
        {timeframe}
        active={activeTab === "questions"}
        {refreshToken}
      ></QuestionTable>
    </Page.Tab>
  </Page.Main>
</Page.Root>

<style>
  @keyframes nordic-fade-in {
    from {
      opacity: 0;
      transform: translateY(4px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }
  .filter-bar {
    animation: nordic-fade-in 0.4s cubic-bezier(0.25, 0.46, 0.45, 0.94) both;
    animation-delay: var(--delay);
  }
</style>
