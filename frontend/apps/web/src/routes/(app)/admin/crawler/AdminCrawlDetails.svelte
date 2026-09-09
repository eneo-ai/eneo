<script lang="ts">
  import { untrack } from "svelte";
  import dayjs from "dayjs";
  import type {
    AdminCrawlerDetails,
    AdminCrawlerRelatedPage,
    CrawlRun,
    WebsiteCrawlRunPage
  } from "@eneo/eneo-js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as Tabs from "$lib/components/ui/tabs/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import { getErrorMessage } from "$lib/core/errors";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import CrawlRunDetailsContent from "$lib/features/knowledge/CrawlRunDetailsContent.svelte";
  import {
    crawlRunState,
    crawlRunStateLabel,
    isActiveCrawlRun
  } from "$lib/features/knowledge/crawlRunState";
  import { m } from "$lib/paraglide/messages";

  let {
    id,
    open = $bindable(false),
    onselect,
    onchange
  }: {
    id: string;
    open?: boolean;
    onselect: (id: string) => void;
    onchange: () => void;
  } = $props();
  const eneo = getEneo();
  let details = $state<AdminCrawlerDetails | null>(null);
  let loading = $state(false);
  let loadFailed = $state(false);
  let view = $state("details");
  let history = $state<WebsiteCrawlRunPage | null>(null);
  let historyCursors = $state<(string | null)[]>([null]);
  let historyLoading = $state(false);
  let historyFailed = $state(false);
  let matches = $state<AdminCrawlerRelatedPage | null>(null);
  let matchCursors = $state<(string | null)[]>([null]);
  let matchesLoading = $state(false);
  let matchesFailed = $state(false);
  let confirmation = $state<"start" | "cancel" | null>(null);
  let busy = $state(false);
  let actionError = $state<string | null>(null);
  let generation = 0;
  let detailRequest = 0;

  const otherActive = $derived(details?.active_run?.id !== id ? details?.active_run : null);
  const retry = $derived(["failed", "interrupted", "partial"].includes(details?.run.outcome ?? ""));
  const startLabel = $derived(retry ? m.admin_crawler_retry_crawl() : m.run_crawl_again());
  const websiteName = $derived(details?.website_name || details?.website_url || m.website());
  const schedule = $derived(
    details?.update_interval === "daily"
      ? m.daily()
      : details?.update_interval === "every_other_day"
        ? m.every_other_day()
        : details?.update_interval === "weekly"
          ? m.weekly()
          : m.never()
  );

  function date(value: string | null | undefined) {
    return value ? dayjs(value).format("YYYY-MM-DD HH:mm") : "—";
  }

  async function loadDetails(fallbackRun?: CrawlRun) {
    const context = generation;
    const request = ++detailRequest;
    loading = true;
    loadFailed = false;
    try {
      const result = await eneo.adminCrawler.details({ id });
      if (open && context === generation && request === detailRequest) details = result;
    } catch {
      if (open && context === generation && request === detailRequest) {
        loadFailed = true;
        if (details && fallbackRun) details = { ...details, run: fallbackRun };
      }
    } finally {
      if (context === generation && request === detailRequest) loading = false;
    }
  }

  $effect(() => {
    if (open && id)
      untrack(() => {
        generation += 1;
        details = null;
        history = null;
        matches = null;
        historyCursors = [null];
        matchCursors = [null];
        historyLoading = false;
        matchesLoading = false;
        historyFailed = false;
        matchesFailed = false;
        confirmation = null;
        actionError = null;
        busy = false;
        view = "details";
        void loadDetails();
      });
    return () => {
      generation += 1;
    };
  });

  async function loadHistory() {
    if (!details || historyLoading) return;
    const context = generation;
    historyLoading = true;
    historyFailed = false;
    try {
      const result = await eneo.adminCrawler.history({
        id: details.website_id,
        limit: 10,
        cursor: historyCursors.at(-1)
      });
      if (open && context === generation) history = result;
    } catch {
      if (open && context === generation) historyFailed = true;
    } finally {
      if (context === generation) historyLoading = false;
    }
  }

  async function loadMatches() {
    if (!details || matchesLoading) return;
    const context = generation;
    matchesLoading = true;
    matchesFailed = false;
    try {
      const result = await eneo.adminCrawler.matches({
        id: details.website_id,
        limit: 10,
        cursor: matchCursors.at(-1)
      });
      if (open && context === generation) matches = result;
    } catch {
      if (open && context === generation) matchesFailed = true;
    } finally {
      if (context === generation) matchesLoading = false;
    }
  }

  function changeView(value: string) {
    view = value;
    if (value === "history" && !history) void loadHistory();
    if (value === "matches" && !matches) void loadMatches();
  }

  async function act() {
    if (!details || !confirmation || busy) return;
    const context = generation;
    const operation = confirmation;
    busy = true;
    actionError = null;
    try {
      const result =
        operation === "start"
          ? await eneo.adminCrawler.start({ id: details.website_id })
          : await eneo.adminCrawler.cancel({ id });
      onchange();
      if (!open || context !== generation) return;
      confirmation = null;
      view = "details";
      history = null;
      historyCursors = [null];
      if (result.id !== id) onselect(result.id);
      else await loadDetails(result);
    } catch (error) {
      if (open && context === generation)
        actionError = getErrorMessage(error, m.admin_crawler_action_error());
    } finally {
      if (context === generation) busy = false;
    }
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Content class="flex max-h-[90dvh] flex-col sm:max-w-3xl" closeLabel={m.close()}>
    <Dialog.Header class="min-w-0 pr-8">
      <Dialog.Title class="break-words">{websiteName}</Dialog.Title>
      <Dialog.Description class="break-all"
        >{details?.website_url ?? m.crawl_details_description()}</Dialog.Description
      >
    </Dialog.Header>

    {#if loadFailed}
      <Alert.Root variant="destructive">
        <Alert.Description>{m.admin_crawler_details_error()}</Alert.Description>
        <Alert.Action
          ><Button variant="outline" disabled={loading || busy} onclick={() => loadDetails()}
            >{m.retry()}</Button
          ></Alert.Action
        >
      </Alert.Root>
    {/if}
    {#if !details && !loadFailed}
      <div class="flex flex-col gap-3" role="status" aria-label={m.loading()}>
        <Skeleton class="h-24 w-full" /><Skeleton class="h-36 w-full" />
      </div>
    {:else if details}
      <Tabs.Root value={view} onValueChange={changeView} class="flex min-h-0 flex-col gap-3">
        <Tabs.List aria-label={m.crawl_details_description()}>
          <Tabs.Trigger value="details">{m.details()}</Tabs.Trigger>
          <Tabs.Trigger value="history">{m.history()}</Tabs.Trigger>
          <Tabs.Trigger value="matches">{m.admin_crawler_same_address()}</Tabs.Trigger>
        </Tabs.List>
        <Tabs.Content value="details" class="min-h-0 overflow-auto">
          <div class="flex flex-col gap-4 pr-1" aria-busy={loading}>
            <dl class="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
              <div class="min-w-0">
                <dt class="text-secondary">{m.admin_crawler_owning_space()}</dt>
                <dd class="mt-1 break-words">
                  {details.space_name ?? m.admin_crawler_not_recorded()}
                </dd>
              </div>
              <div class="min-w-0">
                <dt class="text-secondary">{m.admin_crawler_source_owner()}</dt>
                <dd class="mt-1 break-words">{details.owner.username || details.owner.email}</dd>
                <dd class="text-secondary break-all text-xs">
                  {details.owner.username ? details.owner.email : ""}
                </dd>
              </div>
              <div class="min-w-0">
                <dt class="text-secondary">{m.admin_crawler_initiated_by()}</dt>
                <dd class="mt-1 break-words">
                  {details.run.origin === "scheduled"
                    ? m.crawl_origin_scheduled()
                    : details.initiated_by?.username ||
                      details.initiated_by?.email ||
                      m.admin_crawler_not_recorded()}
                </dd>
              </div>
              <div>
                <dt class="text-secondary">{m.admin_crawler_schedule()}</dt>
                <dd class="mt-1">{schedule}</dd>
              </div>
              <div>
                <dt class="text-secondary">{m.admin_crawler_stored_documents()}</dt>
                <dd class="mt-1 tabular-nums">{details.stored_resources}</dd>
              </div>
              <div>
                <dt class="text-secondary">{m.admin_crawler_indexed_storage()}</dt>
                <dd class="mt-1 tabular-nums">{formatBytes(details.indexed_size, 1)}</dd>
              </div>
              <div>
                <dt class="text-secondary">{m.admin_crawler_last_indexed()}</dt>
                <dd class="mt-1">{date(details.last_indexed_at)}</dd>
              </div>
              <div>
                <dt class="text-secondary">{m.admin_crawler_latest_crawl()}</dt>
                <dd class="mt-1">{date(details.latest_run?.created_at)}</dd>
              </div>
            </dl>
            <p class="text-secondary text-xs">{m.admin_crawler_storage_help()}</p>
            {#if details.consecutive_failures > 0}<p class="text-secondary text-sm">
                {m.admin_crawler_consecutive_failures({ count: details.consecutive_failures })}
              </p>{/if}
            {#if details.next_retry_at}<p class="text-secondary text-sm">
                {m.admin_crawler_retry_after({ time: date(details.next_retry_at) })}
              </p>{/if}
            {#if details.latest_run && details.latest_run.id !== id && !otherActive}
              <Button
                variant="outline"
                class="self-start"
                disabled={busy}
                onclick={() => details?.latest_run && onselect(details.latest_run.id)}
                >{m.admin_crawler_view_latest()}</Button
              >
            {/if}
            <div class="border-default border-t pt-4">
              <h3 class="font-medium">
                {m.crawl_details_title({ date: date(details.run.created_at) })}
              </h3>
              {#if details.started_at}<p class="text-secondary mt-1 text-xs">
                  {m.admin_crawler_started({ time: date(details.started_at) })}
                </p>{/if}
            </div>
            <CrawlRunDetailsContent
              run={details.run}
              {open}
              fetchFailures={eneo.adminCrawler.failures}
              onrefresh={() => loadDetails()}
            />
          </div>
        </Tabs.Content>
        <Tabs.Content value="history" class="min-h-0 overflow-auto">
          <div class="flex flex-col gap-3" aria-busy={historyLoading}>
            {#if historyFailed}
              <Alert.Root variant="destructive"
                ><Alert.Description>{m.admin_crawler_history_error()}</Alert.Description
                ><Alert.Action
                  ><Button variant="outline" onclick={loadHistory}>{m.retry()}</Button
                  ></Alert.Action
                ></Alert.Root
              >
            {/if}
            {#if !history && historyLoading}<Skeleton class="h-40 w-full" />{:else if history}
              <Table.Root>
                <Table.Header
                  ><Table.Row
                    ><Table.Head>{m.admin_crawler_requested()}</Table.Head><Table.Head
                      >{m.status()}</Table.Head
                    ><Table.Head>{m.admin_crawler_result()}</Table.Head></Table.Row
                  ></Table.Header
                >
                <Table.Body
                  >{#each history.items as entry (entry.id)}
                    <Table.Row>
                      <Table.Cell
                        ><Button
                          variant="link"
                          class="h-auto p-0 text-left whitespace-normal"
                          disabled={busy}
                          aria-label={m.admin_crawler_select_run({ date: date(entry.created_at) })}
                          onclick={() => {
                            view = "details";
                            onselect(entry.id);
                          }}>{date(entry.created_at)}</Button
                        ></Table.Cell
                      >
                      <Table.Cell
                        ><Badge variant="secondary"
                          >{crawlRunStateLabel(crawlRunState(entry))}</Badge
                        ></Table.Cell
                      >
                      <Table.Cell class="whitespace-normal text-xs"
                        >{m.pages_succeeded({ count: entry.pages_crawled ?? "—" })}<br
                        />{m.files_succeeded({ count: entry.files_downloaded ?? "—" })}</Table.Cell
                      >
                    </Table.Row>
                  {/each}</Table.Body
                >
              </Table.Root>
              <div class="flex justify-end gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={historyCursors.length === 1 || historyLoading}
                  onclick={() => {
                    historyCursors = historyCursors.slice(0, -1);
                    history = null;
                    void loadHistory();
                  }}>{m.admin_crawler_previous()}</Button
                >
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!history.next_cursor || historyLoading}
                  onclick={() => {
                    if (history?.next_cursor) {
                      historyCursors = [...historyCursors, history.next_cursor];
                      history = null;
                      void loadHistory();
                    }
                  }}>{m.admin_crawler_next()}</Button
                >
              </div>
            {/if}
          </div>
        </Tabs.Content>
        <Tabs.Content value="matches" class="min-h-0 overflow-auto">
          <div class="flex flex-col gap-3" aria-busy={matchesLoading}>
            <p class="text-secondary text-sm">{m.admin_crawler_same_address_description()}</p>
            {#if matchesFailed}<Alert.Root variant="destructive"
                ><Alert.Description>{m.admin_crawler_matches_error()}</Alert.Description
                ><Alert.Action
                  ><Button variant="outline" onclick={loadMatches}>{m.retry()}</Button
                  ></Alert.Action
                ></Alert.Root
              >{/if}
            {#if !matches && matchesLoading}<Skeleton class="h-32 w-full" />{:else if matches}
              {#each matches.items as source (source.website_id)}
                <div
                  class="border-default flex min-w-0 flex-wrap items-start justify-between gap-3 border-b pb-3"
                >
                  <div class="min-w-0 flex-1">
                    {#if source.latest_run_id}<Button
                        variant="link"
                        class="h-auto max-w-full p-0 text-left break-all whitespace-normal"
                        disabled={busy}
                        onclick={() => source.latest_run_id && onselect(source.latest_run_id)}
                        >{source.website_name || source.website_url}</Button
                      >
                    {:else}<p class="break-all">{source.website_name || source.website_url}</p>{/if}
                    <p class="text-secondary mt-1 text-sm break-words">
                      {source.space_name ?? m.admin_crawler_not_recorded()}
                    </p>
                    <p class="text-secondary mt-1 text-xs">
                      {source.latest_run_id
                        ? `${m.admin_crawler_last_indexed()}: ${date(source.last_indexed_at)}`
                        : m.admin_crawler_no_run()}
                    </p>
                  </div>
                  <p class="text-secondary text-sm tabular-nums">
                    {formatBytes(source.indexed_size, 1)}
                  </p>
                </div>
              {:else}<p class="text-secondary py-6 text-sm">
                  {m.admin_crawler_same_address_empty()}
                </p>{/each}
              {#if matchCursors.length > 1 || matches.next_cursor}<div
                  class="flex justify-end gap-2"
                >
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={matchCursors.length === 1 || matchesLoading}
                    onclick={() => {
                      matchCursors = matchCursors.slice(0, -1);
                      matches = null;
                      void loadMatches();
                    }}>{m.admin_crawler_previous()}</Button
                  >
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={!matches.next_cursor || matchesLoading}
                    onclick={() => {
                      if (matches?.next_cursor) {
                        matchCursors = [...matchCursors, matches.next_cursor];
                        matches = null;
                        void loadMatches();
                      }
                    }}>{m.admin_crawler_next()}</Button
                  >
                </div>{/if}
            {/if}
          </div>
        </Tabs.Content>
      </Tabs.Root>

      <div class="border-default flex flex-col gap-3 border-t pt-3">
        {#if actionError && !confirmation}<p role="alert" class="text-negative-default text-sm">
            {actionError}
          </p>{/if}
        {#if otherActive}
          <div class="flex flex-wrap items-center justify-between gap-2">
            <p class="text-secondary text-sm">{m.admin_crawler_newer_active()}</p>
            <Button
              variant="outline"
              disabled={busy}
              onclick={() => otherActive && onselect(otherActive.id)}
              >{m.admin_crawler_view_active()}</Button
            >
          </div>
        {:else if isActiveCrawlRun(details.run)}
          <Button
            class="self-end"
            variant="destructive"
            disabled={busy || loading || details.run.phase === "stopping"}
            onclick={() => {
              actionError = null;
              confirmation = "cancel";
            }}>{details.run.phase === "stopping" ? m.stopping_crawl() : m.stop_crawl()}</Button
          >
        {:else}
          <Button
            class="self-end"
            disabled={busy || loading}
            onclick={() => {
              actionError = null;
              confirmation = "start";
            }}>{busy ? m.starting() : startLabel}</Button
          >
        {/if}
      </div>
    {/if}
  </Dialog.Content>
</Dialog.Root>

<AlertDialog.Root
  open={confirmation !== null && open}
  onOpenChange={(value) => {
    if (!value && !busy) confirmation = null;
  }}
>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title
        >{confirmation === "cancel" ? m.stop_crawl_title() : startLabel}</AlertDialog.Title
      >
      <AlertDialog.Description class="break-words"
        >{confirmation === "cancel"
          ? m.stop_crawl_description({ websiteName })
          : m.admin_crawler_rerun_description({ websiteName })}</AlertDialog.Description
      >
    </AlertDialog.Header>
    {#if actionError}<p role="alert" class="text-negative-default text-sm">{actionError}</p>{/if}
    <AlertDialog.Footer>
      <AlertDialog.Cancel disabled={busy}>{m.cancel()}</AlertDialog.Cancel>
      <Button
        variant={confirmation === "cancel" ? "destructive" : "default"}
        disabled={busy}
        aria-busy={busy}
        onclick={act}
        >{confirmation === "cancel"
          ? busy
            ? m.stopping_crawl()
            : m.stop_crawl()
          : busy
            ? m.starting()
            : startLabel}</Button
      >
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
