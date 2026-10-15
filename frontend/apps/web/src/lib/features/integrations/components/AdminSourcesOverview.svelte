<script lang="ts">
  import { onMount } from "svelte";
  import type { Eneo, components } from "@eneo/eneo-js";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { getErrorMessage } from "$lib/core/errors";
  import { formatRelativeTime } from "$lib/core/formatting/dateTime";
  import IntegrationVendorIcon from "$lib/features/integrations/components/IntegrationVendorIcon.svelte";
  import SourceStateBadge from "$lib/features/integrations/components/SourceStateBadge.svelte";
  import SourceStatusFilter from "$lib/features/integrations/components/SourceStatusFilter.svelte";
  import { isCredentialsError } from "$lib/features/integrations/sourceProblems";
  import {
    countSourceFilters,
    groupSourcesBySpace,
    matchesSourceFilter,
    sourceContentsLabel,
    sourceHref,
    summarizeSource,
    type IntegrationSource,
    type SourceFilter,
    type SourceSummary
  } from "$lib/features/integrations/sources";
  import { m } from "$lib/paraglide/messages";

  type OverviewSpace = components["schemas"]["AdminIntegrationKnowledgeSpace"];
  type Overview = components["schemas"]["AdminIntegrationKnowledgeOverview"];

  interface Props {
    eneo: Eneo;
  }

  let { eneo }: Props = $props();

  type Row = { space: OverviewSpace; source: IntegrationSource; summary: SourceSummary };

  let overview = $state<Overview | null>(null);
  let error = $state<string | null>(null);
  let loading = $state(false);
  let filter = $state<SourceFilter>("all");
  let query = $state("");

  async function load() {
    loading = true;
    error = null;
    try {
      overview = (await eneo.integrations.admin.knowledgeOverview()) as Overview;
    } catch (err) {
      error = getErrorMessage(err);
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    void load();
  });

  let rows = $derived.by((): Row[] =>
    groupSourcesBySpace(overview?.items ?? []).map(({ space, source }) => ({
      space,
      source,
      summary: summarizeSource(source.items, {})
    }))
  );

  let counts = $derived(countSourceFilters(rows.map((row) => row.summary)));
  let attentionSpaces = $derived(
    new Set(rows.filter((row) => row.summary.failedItems.length > 0).map((row) => row.space.id))
      .size
  );
  let documentTotal = $derived(rows.reduce((sum, row) => sum + row.summary.documentCount, 0));

  function matchesQuery(row: Row, needle: string): boolean {
    if (needle === "") return true;
    return [row.source.name, row.space.name, ...row.source.items.map((item) => item.name)].some(
      (text) => text.toLowerCase().includes(needle)
    );
  }

  let visible = $derived(
    rows
      .filter(
        (row) =>
          matchesSourceFilter(row.summary, filter) && matchesQuery(row, query.trim().toLowerCase())
      )
      // Whatever needs someone comes first; the rest by space, then source.
      .sort(
        (a, b) =>
          Number(b.summary.failedItems.length > 0) - Number(a.summary.failedItems.length > 0) ||
          a.space.name.localeCompare(b.space.name) ||
          a.source.name.localeCompare(b.source.name)
      )
  );

  /** Why the source needs attention: its first failure, in words for the known sign-in one. */
  function failureText(summary: SourceSummary): string | null {
    const message = summary.failedItems[0]?.metadata?.last_sync_error?.trim();
    if (!message) return null;
    return isCredentialsError(message) ? m.integration_problem_credentials_title() : message;
  }

  function updatedLabel(summary: SourceSummary): string {
    if (summary.lastSyncedAt) return formatRelativeTime(summary.lastSyncedAt);
    if (summary.lastSyncAttemptedAt) {
      return m.integration_source_last_attempt_at({
        time: formatRelativeTime(summary.lastSyncAttemptedAt)
      });
    }
    return "–";
  }
</script>

<section aria-labelledby="admin-sources-heading" class="flex flex-col gap-4">
  <h3 id="admin-sources-heading" class="sr-only">{m.admin_sources_heading()}</h3>

  {#if loading && !overview}
    <div class="text-secondary flex items-center gap-2 text-sm" role="status">
      <IconLoadingSpinner size="sm" class="motion-safe:animate-spin" />
      <span>{m.loading()}</span>
    </div>
  {:else if error}
    <div
      class="text-negative-stronger bg-negative-dimmer flex flex-wrap items-center gap-3 rounded p-4 text-sm"
      role="alert"
    >
      <span>{m.admin_sources_load_failed()}: {error}</span>
      <Button variant="outline" size="sm" onclick={load}>{m.retry()}</Button>
    </div>
  {:else if overview}
    <dl class="border-default grid grid-cols-2 rounded-lg border md:grid-cols-4">
      <div class="flex flex-col gap-1 px-4 py-3">
        <dt class="text-secondary text-xs">{m.admin_sources_stat_sources()}</dt>
        <dd class="text-xl font-semibold tabular-nums">{rows.length}</dd>
      </div>
      <div class="border-default flex flex-col gap-1 border-l px-4 py-3">
        <dt class="text-secondary text-xs">{m.admin_sources_stat_attention()}</dt>
        <dd
          class="text-xl font-semibold tabular-nums {counts.attention > 0
            ? 'text-negative-stronger'
            : ''}"
        >
          {counts.attention}
          {#if attentionSpaces > 0}
            <span class="text-secondary text-xs font-normal">
              {attentionSpaces === 1
                ? m.admin_sources_in_spaces_one()
                : m.admin_sources_in_spaces_other({ count: attentionSpaces })}
            </span>
          {/if}
        </dd>
      </div>
      <div class="border-default flex flex-col gap-1 px-4 py-3 max-md:border-t md:border-l">
        <dt class="text-secondary text-xs">{m.admin_sources_stat_documents()}</dt>
        <dd class="text-xl font-semibold tabular-nums">{documentTotal}</dd>
      </div>
      <div class="border-default flex flex-col gap-1 border-l px-4 py-3 max-md:border-t">
        <dt class="text-secondary text-xs">{m.admin_sources_stat_personal()}</dt>
        <dd class="text-xl font-semibold tabular-nums">
          {overview.personal.items}
          {#if overview.personal.failing > 0}
            <span class="text-negative-stronger text-xs font-normal">
              {m.admin_sources_personal_failing({ count: overview.personal.failing })}
            </span>
          {/if}
        </dd>
      </div>
    </dl>

    {#if rows.length === 0}
      <p class="text-secondary py-4 text-sm">{m.admin_sources_none()}</p>
    {:else}
      <div class="flex flex-wrap items-center justify-between gap-3">
        <SourceStatusFilter {counts} bind:value={filter} />
        <Input
          type="search"
          bind:value={query}
          aria-label={m.admin_sources_search()}
          placeholder={m.admin_sources_search()}
          class="max-w-xs"
        />
      </div>

      <Table.Root aria-label={m.admin_sources_heading()}>
        <Table.Header>
          <Table.Row>
            <Table.Head>{m.integration_source_column_source()}</Table.Head>
            <Table.Head>{m.admin_sources_column_space()}</Table.Head>
            <Table.Head class="text-right">{m.documents()}</Table.Head>
            <Table.Head>{m.status()}</Table.Head>
            <Table.Head>{m.integration_source_last_up_to_date()}</Table.Head>
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {#each visible as row (`${row.space.id}:${row.source.kind}:${row.source.id}`)}
            <Table.Row>
              <Table.Cell>
                <div class="flex min-w-0 items-center gap-3">
                  <IntegrationVendorIcon size="sm" type={row.source.integrationType} />
                  <div class="flex min-w-0 flex-col">
                    {#if row.space.can_open}
                      <!-- eslint-disable svelte/no-navigation-without-resolve -- dynamic space route -->
                      <a
                        href={sourceHref(row.space.id, row.source)}
                        class="focus-visible:ring-stronger truncate rounded font-medium hover:underline focus-visible:ring-2 focus-visible:outline-none"
                      >
                        {row.source.name}
                      </a>
                      <!-- eslint-enable svelte/no-navigation-without-resolve -->
                    {:else}
                      <span class="truncate font-medium">{row.source.name}</span>
                    {/if}
                    <span class="text-secondary truncate text-xs">
                      {sourceContentsLabel(row.source.items)}
                    </span>
                  </div>
                </div>
              </Table.Cell>
              <Table.Cell>
                {row.space.name}
                {#if row.space.organization}
                  <span class="text-secondary text-xs">({m.organization()})</span>
                {/if}
              </Table.Cell>
              <Table.Cell class="text-right tabular-nums">{row.summary.documentCount}</Table.Cell>
              <Table.Cell>
                {@const failure = failureText(row.summary)}
                <div class="flex max-w-xs flex-col items-start gap-1">
                  <SourceStateBadge state={row.summary.state} />
                  {#if failure}
                    <span class="text-secondary text-xs break-words">{failure}</span>
                  {:else if row.summary.waitingItems > 0 && row.summary.state !== "never"}
                    <span class="text-secondary text-xs">
                      {row.summary.waitingItems === 1
                        ? m.integration_source_waiting_one()
                        : m.integration_source_waiting_other({ count: row.summary.waitingItems })}
                    </span>
                  {/if}
                </div>
              </Table.Cell>
              <Table.Cell class="text-secondary">{updatedLabel(row.summary)}</Table.Cell>
            </Table.Row>
          {:else}
            <Table.Row>
              <Table.Cell colspan={5} class="text-secondary py-6 text-center">
                {m.no_results_found()}
              </Table.Cell>
            </Table.Row>
          {/each}
        </Table.Body>
      </Table.Root>
    {/if}
  {/if}
</section>
