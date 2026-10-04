<script lang="ts">
  import type { FlowRetentionHold, FlowRetentionHoldPage } from "@eneo/eneo-js";
  import Gavel from "@lucide/svelte/icons/gavel";
  import { untrack } from "svelte";

  import { Settings } from "$lib/components/layout";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import * as ToggleGroup from "$lib/components/ui/toggle-group/index.js";
  import { toastError } from "$lib/core/errors";
  import { getEneo } from "$lib/core/Eneo";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";

  import FlowRetentionHoldChangeDialog from "./FlowRetentionHoldChangeDialog.svelte";
  import FlowRetentionHoldPlaceDialog from "./FlowRetentionHoldPlaceDialog.svelte";
  import { holdScopeLabel, holdState } from "./flowRetentionHold";

  type Props = {
    initialHolds: FlowRetentionHoldPage | null;
    // The review limit, or null when it could not be read: then no hold can be
    // placed or reviewed here, because the dates cannot be checked.
    maxReviewDays: number | null;
    selectedFlow: { id: string; name: string } | null;
    onHoldsChanged?: () => void;
    // The holds list carries the current limit; the panel keeps one value.
    onReviewLimit?: (days: number) => void;
  };

  let { initialHolds, maxReviewDays, selectedFlow, onHoldsChanged, onReviewLimit }: Props =
    $props();
  const eneo = getEneo();
  const PAGE_SIZE = 200;

  let holds = $state<FlowRetentionHold[]>(untrack(() => initialHolds?.items ?? []));
  let unavailable = $state(untrack(() => initialHolds === null));
  let hasMore = $state(untrack(() => initialHolds?.has_more ?? false));
  // Pages through the list with the API's offset, so every hold can be reached.
  let offset = $state(0);
  let loading = $state(false);
  // A reload asked for while one runs (view switched, hold placed) runs after it.
  let reloadQueued = false;
  // "all" keeps released and ended holds in view: who stopped gallring, why, when and until when.
  let view = $state<"active" | "all">("active");

  let placeOpen = $state(false);
  let placeFlow = $state<{ id: string; name: string } | null>(null);
  let changeTarget = $state<FlowRetentionHold | null>(null);
  let changeMode = $state<"release" | "extend">("release");

  const dateFormatter = new Intl.DateTimeFormat(getLocale(), {
    dateStyle: "medium",
    timeStyle: "short"
  });
  const dayFormatter = new Intl.DateTimeFormat(getLocale(), { dateStyle: "medium" });

  function formatDate(value: string): string {
    return dateFormatter.format(new Date(value));
  }

  function chooseView(value: string | undefined): void {
    if ((value !== "active" && value !== "all") || value === view) return;
    view = value;
    offset = 0;
    void reload();
  }

  function goToPage(nextOffset: number): void {
    offset = Math.max(0, nextOffset);
    void reload();
  }

  function fetchPage() {
    return eneo.settings.listFlowRetentionHolds({ status: view, limit: PAGE_SIZE, offset });
  }

  async function reload(): Promise<void> {
    if (loading) {
      reloadQueued = true;
      return;
    }
    loading = true;
    try {
      do {
        reloadQueued = false;
        try {
          let page = await fetchPage();
          // A page can empty out under the reader: its last hold released or
          // ended here or elsewhere. Step back to the nearest page with holds;
          // offset only decreases, so this stops at the first page at the latest.
          while (page.items.length === 0 && offset > 0) {
            offset = Math.max(0, offset - PAGE_SIZE);
            page = await fetchPage();
          }
          holds = page.items;
          hasMore = page.has_more;
          unavailable = false;
          onReviewLimit?.(page.review_limit_days);
        } catch (error) {
          unavailable = true;
          toastError(error);
        }
      } while (reloadQueued);
    } finally {
      loading = false;
    }
  }

  async function changed(): Promise<void> {
    onHoldsChanged?.();
    await reload();
  }

  function openPlace(): void {
    if (!selectedFlow) return;
    placeFlow = selectedFlow;
    placeOpen = true;
  }

  function openChange(hold: FlowRetentionHold, mode: "release" | "extend"): void {
    changeMode = mode;
    changeTarget = hold;
  }
</script>

<Settings.Group
  title={m.flow_retention_hold_group()}
  description={m.flow_retention_hold_group_description()}
  density="compact"
>
  <Card.Root class="mx-4 lg:mx-0.5">
    <Card.Header>
      <Card.Title class="flex items-center gap-2">
        <Gavel class="size-4" aria-hidden="true" />
        {view === "active"
          ? m.flow_retention_hold_active_title()
          : m.flow_retention_hold_all_title()}
      </Card.Title>
      <Card.Description>
        {selectedFlow
          ? m.flow_retention_hold_active_description()
          : m.flow_retention_hold_place_needs_flow()}
      </Card.Description>
      <Card.Action class="flex flex-wrap items-center justify-end gap-2">
        <ToggleGroup.Root
          type="single"
          variant="outline"
          size="sm"
          spacing={0}
          bind:value={() => view, chooseView}
          aria-label={m.flow_retention_hold_view_label()}
        >
          <ToggleGroup.Item value="active" class="px-3">
            {m.flow_retention_hold_view_active()}
          </ToggleGroup.Item>
          <ToggleGroup.Item value="all" class="px-3">
            {m.flow_retention_hold_view_all()}
          </ToggleGroup.Item>
        </ToggleGroup.Root>
        <Button type="button" variant="outline" size="sm" disabled={loading} onclick={reload}>
          {m.flow_retention_hold_refresh()}
        </Button>
        <Button
          type="button"
          size="sm"
          disabled={!selectedFlow || maxReviewDays === null}
          aria-label={selectedFlow
            ? m.flow_retention_hold_place_for_flow({ flow: selectedFlow.name })
            : m.flow_retention_hold_place()}
          onclick={openPlace}
        >
          {m.flow_retention_hold_place()}
        </Button>
      </Card.Action>
    </Card.Header>
    <Card.Content class="space-y-3">
      {#if maxReviewDays === null}
        <Alert.Root>
          <Alert.Description>{m.flow_retention_hold_limit_unavailable()}</Alert.Description>
        </Alert.Root>
      {/if}
      {#if unavailable}
        <Alert.Root>
          <Alert.Title>{m.flow_retention_hold_unavailable_title()}</Alert.Title>
          <Alert.Description>{m.flow_retention_hold_unavailable_description()}</Alert.Description>
        </Alert.Root>
      {:else if holds.length === 0 && offset > 0}
        <!-- Only while a step back is pending: this page is empty, not the list. -->
        <p class="text-secondary text-sm">{m.flow_retention_hold_page_empty()}</p>
      {:else if holds.length === 0}
        <div class="border-default bg-secondary rounded-md border p-4">
          <p class="text-primary text-sm font-medium">
            {view === "active"
              ? m.flow_retention_hold_empty_title()
              : m.flow_retention_hold_empty_all_title()}
          </p>
          <p class="text-secondary mt-1 text-sm">{m.flow_retention_hold_empty_description()}</p>
        </div>
      {:else}
        <div class="border-default overflow-x-auto rounded-md border">
          <Table.Root>
            <Table.Header>
              <Table.Row>
                <Table.Head>{m.flow_retention_hold_column_scope()}</Table.Head>
                <Table.Head>{m.flow_retention_hold_column_reason()}</Table.Head>
                <Table.Head>{m.flow_retention_hold_column_placed()}</Table.Head>
                <Table.Head>{m.flow_retention_hold_column_review()}</Table.Head>
                <Table.Head>{m.flow_retention_hold_column_ends()}</Table.Head>
                <Table.Head>{m.flow_retention_hold_column_status()}</Table.Head>
                <Table.Head
                  ><span class="sr-only">{m.flow_retention_hold_column_actions()}</span></Table.Head
                >
              </Table.Row>
            </Table.Header>
            <Table.Body>
              {#each holds as hold (hold.id)}
                {@const state = holdState(hold)}
                <Table.Row>
                  <Table.Cell>
                    <div class="min-w-48">
                      <p class="text-primary flex items-center gap-2 font-medium">
                        <span class="truncate">{hold.flow_name}</span>
                        {#if hold.flow_retired}
                          <Badge variant="outline">{m.flow_run_retention_target_retired()}</Badge>
                        {/if}
                      </p>
                      <p class="text-secondary text-xs break-all">{holdScopeLabel(hold)}</p>
                    </div>
                  </Table.Cell>
                  <Table.Cell>
                    <p class="max-w-72 text-sm break-words whitespace-pre-line">{hold.reason}</p>
                  </Table.Cell>
                  <Table.Cell>
                    <div class="min-w-36 text-sm">
                      <p class="text-primary">
                        {hold.created_by?.name ?? m.flow_retention_hold_unknown_actor()}
                      </p>
                      <p class="text-secondary text-xs tabular-nums">
                        {formatDate(hold.created_at)}
                      </p>
                    </div>
                  </Table.Cell>
                  <Table.Cell>
                    <div class="flex min-w-32 flex-col items-start gap-1 text-sm tabular-nums">
                      <span>{dayFormatter.format(new Date(hold.review_by))}</span>
                      {#if hold.review_overdue}
                        <Badge variant="destructive">{m.flow_retention_hold_review_overdue()}</Badge
                        >
                      {/if}
                    </div>
                  </Table.Cell>
                  <Table.Cell class="whitespace-nowrap tabular-nums">
                    {hold.ends_at ? formatDate(hold.ends_at) : m.flow_retention_hold_no_end()}
                  </Table.Cell>
                  <Table.Cell>
                    {#if state === "active"}
                      <Badge variant="secondary">{m.flow_retention_hold_state_active()}</Badge>
                    {:else if state === "ended"}
                      <Badge variant="outline">{m.flow_retention_hold_state_ended()}</Badge>
                    {:else}
                      <div class="min-w-44 text-sm">
                        <Badge variant="outline">{m.flow_retention_hold_state_released()}</Badge>
                        <p class="text-secondary mt-1 text-xs">
                          {m.flow_retention_hold_released_by({
                            name: hold.released_by?.name ?? m.flow_retention_hold_unknown_actor(),
                            date: hold.released_at ? formatDate(hold.released_at) : ""
                          })}
                        </p>
                        {#if hold.release_reason}
                          <p class="mt-0.5 max-w-60 text-xs break-words whitespace-pre-line">
                            {hold.release_reason}
                          </p>
                        {/if}
                      </div>
                    {/if}
                  </Table.Cell>
                  <Table.Cell class="text-right">
                    {#if hold.active}
                      <div class="flex justify-end gap-2">
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          disabled={maxReviewDays === null}
                          aria-label={m.flow_retention_hold_extend_label({
                            scope: holdScopeLabel(hold)
                          })}
                          onclick={() => openChange(hold, "extend")}
                        >
                          {m.flow_retention_hold_extend()}
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          aria-label={m.flow_retention_hold_release_label({
                            scope: holdScopeLabel(hold)
                          })}
                          onclick={() => openChange(hold, "release")}
                        >
                          {m.flow_retention_hold_release()}
                        </Button>
                      </div>
                    {/if}
                  </Table.Cell>
                </Table.Row>
              {/each}
            </Table.Body>
          </Table.Root>
        </div>
      {/if}
      {#if hasMore || offset > 0}
        <div class="flex items-center justify-between gap-3">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={loading || offset === 0}
            onclick={() => goToPage(offset - PAGE_SIZE)}
          >
            {m.previous()}
          </Button>
          <span class="text-secondary text-xs tabular-nums">
            {m.flow_retention_hold_page_range({
              from: offset + 1,
              to: offset + holds.length
            })}
          </span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={loading || !hasMore}
            onclick={() => goToPage(offset + PAGE_SIZE)}
          >
            {m.next()}
          </Button>
        </div>
      {/if}
    </Card.Content>
  </Card.Root>
</Settings.Group>

{#if maxReviewDays !== null}
  <FlowRetentionHoldPlaceDialog
    bind:open={placeOpen}
    flow={placeFlow}
    {maxReviewDays}
    onPlaced={changed}
  />

  <FlowRetentionHoldChangeDialog
    hold={changeTarget}
    mode={changeMode}
    {maxReviewDays}
    onChanged={changed}
    onClose={() => (changeTarget = null)}
  />
{/if}
