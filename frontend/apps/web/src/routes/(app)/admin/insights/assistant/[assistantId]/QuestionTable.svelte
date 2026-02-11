<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button, Table } from "@intric/ui";
  import dayjs from "dayjs";
  import { m } from "$lib/paraglide/messages";
  import QuestionDetails from "./QuestionDetails.svelte";
  import { createRender } from "svelte-headless-table";
  import type { CalendarDate } from "@internationalized/date";
  import { getIntric } from "$lib/core/Intric";
  import { onMount } from "svelte";

  type QuestionRow = {
    id: string;
    question: string;
    created_at: string;
    session_id: string;
  };

  type PaginatedQuestionsResponse = {
    items?: QuestionRow[];
    total_count?: number;
    next_cursor?: string | null;
  };

  export let assistantId: string;
  export let intric = getIntric();
  export let includeFollowups: boolean;
  export let timeframe: { start: CalendarDate; end: CalendarDate };
  export let active = false;
  export let refreshToken = 0;

  const PAGE_SIZE = 100;

  let questions: QuestionRow[] = [];
  let totalCount = 0;
  let nextCursor: string | null = null;
  let errorMessage = "";
  let isLoading = false;
  let isLoadingMore = false;
  let lastFetchKey = "";
  let inFlightFetchKey = "";
  let searchQuery = "";
  let activeRequestId = 0;

  const table = Table.createWithResource<QuestionRow>([], 999999, { serverSideFilter: true });

  const viewModel = table.createViewModel([
    table.column({
      header: m.question(),
      accessor: (item) => item,
      cell(item) {
        return createRender(QuestionDetails, {
          message: item.value
        });
      },
      plugins: {
        tableFilter: {
          getFilterValue(item: QuestionRow) {
            return item.question;
          }
        }
      }
    }),
    table.column({
      header: m.created(),
      accessor: (item) => item.created_at,
      cell: (item) => {
        return createRender(Table.FormattedCell, {
          value: dayjs(item.value).format("YYYY-MM-DD HH:mm"),
          monospaced: true
        });
      }
    })
  ]);

  const filterValue = viewModel.pluginStates.tableFilter.filterValue;

  async function fetchQuestions({ reset }: { reset: boolean }) {
    if (!active) return;

    const requestId = ++activeRequestId;
    errorMessage = "";

    if (reset) {
      isLoading = true;
      nextCursor = null;
    } else {
      isLoadingMore = true;
    }

    try {
      const inclusiveEnd = timeframe.end.add({ days: 1 }).toString();
      const response = (await intric.analytics.listQuestionsPaginated({
        assistant: { id: assistantId },
        options: {
          start: timeframe.start.toString(),
          end: inclusiveEnd,
          includeFollowups,
          limit: PAGE_SIZE,
          cursor: reset ? undefined : nextCursor ?? undefined,
          query: searchQuery.trim() || undefined
        }
      })) as PaginatedQuestionsResponse;

      if (requestId !== activeRequestId) return;

      const items = response?.items ?? [];
      questions = reset ? items : [...questions, ...items];
      totalCount = Number(response?.total_count ?? questions.length);
      nextCursor = response?.next_cursor ?? null;
    } catch (error) {
      if (requestId !== activeRequestId) return;
      console.error(error);
      if (reset) {
        questions = [];
        totalCount = 0;
        nextCursor = null;
      }
      errorMessage = m.error_connecting_to_server();
    } finally {
      if (requestId === activeRequestId) {
        isLoading = false;
        isLoadingMore = false;
        if (reset) {
          inFlightFetchKey = "";
        }
      }
    }
  }

  function loadMore() {
    if (!nextCursor || isLoading || isLoadingMore) return;
    void fetchQuestions({ reset: false });
  }

  let searchDebounceTimer: ReturnType<typeof setTimeout> | undefined;
  onMount(() => {
    const unsubscribe = filterValue.subscribe((value: string) => {
      clearTimeout(searchDebounceTimer);
      searchDebounceTimer = setTimeout(() => {
        const normalized = value.trim();
        if (normalized !== searchQuery) {
          searchQuery = normalized;
        }
      }, 250);
    });

    return () => {
      clearTimeout(searchDebounceTimer);
      unsubscribe();
    };
  });

$: fetchKey = [
  assistantId,
  timeframe.start.toString(),
  timeframe.end.toString(),
  includeFollowups ? "1" : "0",
  searchQuery.trim(),
  refreshToken
].join("|");

$: if (active) {
    const fetchKeyLocal = fetchKey;
    if (fetchKeyLocal === lastFetchKey || fetchKeyLocal === inFlightFetchKey) {
      // no-op
    } else {
      inFlightFetchKey = fetchKeyLocal;
      lastFetchKey = fetchKeyLocal;
      void fetchQuestions({ reset: true });
    }
  }

$: table.update(questions ?? []);
</script>

<Table.Root
  {viewModel}
  resourceName="question"
  emptyMessage={isLoading ? m.loading() : m.no_questions_found_current_settings()}
></Table.Root>

<div class="flex flex-col items-center justify-center gap-3 pt-6 pb-10">
  {#if errorMessage}
    <p class="text-sm text-red-700" role="alert">{errorMessage}</p>
  {:else if nextCursor}
    <Button variant="outlined" on:click={loadMore} disabled={isLoading || isLoadingMore}>
      {#if isLoadingMore}
        {m.loading()}
      {:else}
        {m.load_more_conversations()}
      {/if}
    </Button>
    <p class="text-muted text-xs tabular-nums" role="status" aria-live="polite">
      {m.loaded_conversations_count({ loaded: questions.length, total: totalCount })}
    </p>
  {:else if totalCount > 0}
    <div class="mx-auto my-2 h-px w-16 border-t border-dimmer"></div>
    <p class="text-muted text-xs tabular-nums" role="status" aria-live="polite">
      {m.loaded_all_conversations({ total: totalCount })}
    </p>
  {/if}
</div>
