<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Page } from "$lib/components/layout";
  import ChatView from "./ChatView.svelte";
  import { page } from "$app/stores";
  import FilterPopup from "./FilterPopup.svelte";
  import QuestionTable from "./QuestionTable.svelte";
  import { m } from "$lib/paraglide/messages";

  export let data;

  let questions = data.questions;

  let includeFollowups: boolean = data.includeFollowups;
  let timeframe = data.timeframe;

  async function updateQuestions(includeFollowups: boolean, range: typeof timeframe) {
    questions = await data.intric.analytics.listQuestions({
      assistant: { id: $page.params.assistantId },
      options: {
        start: range.start.toString(),
        end: range.end.toString(),
        includeFollowups
      }
    });
  }
</script>

<svelte:head>
  <title>Eneo.ai – Admin – {data.assistant.name} – {m.insights()}</title>
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
    <FilterPopup onUpdate={updateQuestions} {includeFollowups} dateRange={timeframe}></FilterPopup>
  </Page.Header>

  <Page.Main>
    <Page.Tab id="chat">
      <ChatView assistant={data.assistant} {includeFollowups} {timeframe}></ChatView>
    </Page.Tab>
    <Page.Tab id="questions">
      <QuestionTable {questions}></QuestionTable>
    </Page.Tab>
  </Page.Main>
</Page.Root>
