<!--
  Widgets whose editors asked for activation, oldest request first, each
  with a link to its review. Narrow screens fold the space, the request and
  the status into the widget cell, so nothing scrolls sideways.
-->
<script lang="ts">
  import type { WidgetOverviewItem } from "@eneo/eneo-js";
  import { ArrowRight, CircleCheck, TriangleAlert } from "@lucide/svelte";
  import * as Table from "$lib/components/ui/table/index.js";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import { blockerLabel } from "./blockers";
  import TimedText from "./TimedText.svelte";

  type Props = {
    /** Every overview item; those without a pending request are left out. */
    items: readonly WidgetOverviewItem[];
  };

  let { items }: Props = $props();

  const requests = $derived(
    items
      .filter((item) => item.activation_requested_at)
      .sort((a, b) =>
        (a.activation_requested_at ?? "").localeCompare(b.activation_requested_at ?? "")
      )
  );

  const requestedMessage = (item: WidgetOverviewItem) => (date: string) =>
    item.activation_requested_by
      ? m.widget_admin_overview_awaiting_requested({
          date,
          name: item.activation_requested_by.name
        })
      : date;

  const blockedReasons = (item: WidgetOverviewItem) =>
    // Each label is a sentence of its own.
    (item.activation_blockers ?? []).map(blockerLabel).join(" ");
</script>

{#snippet status(item: WidgetOverviewItem)}
  {@const reasons = blockedReasons(item)}
  {#if reasons}
    <span class="text-warning-stronger flex items-start gap-1.5">
      <TriangleAlert class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <span>{m.widget_admin_overview_awaiting_blocked({ reasons })}</span>
    </span>
  {:else}
    <span class="flex items-start gap-1.5">
      <CircleCheck class="text-positive-stronger mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <span>{m.widget_admin_overview_awaiting_ready()}</span>
    </span>
  {/if}
{/snippet}

<div class="border-default bg-primary overflow-hidden rounded-xl border">
  <Table.Root>
    <caption class="sr-only">{m.widget_admin_overview_awaiting_caption()}</caption>
    <Table.Header>
      <Table.Row class="hover:bg-transparent">
        <Table.Head scope="col" class="px-4">{m.widget_admin_title()}</Table.Head>
        <Table.Head scope="col" class="hidden px-4 md:table-cell">
          {m.widget_review_space()}
        </Table.Head>
        <Table.Head scope="col" class="hidden px-4 lg:table-cell">
          {m.widget_admin_overview_awaiting_requested_column()}
        </Table.Head>
        <Table.Head scope="col" class="hidden px-4 lg:table-cell">{m.status()}</Table.Head>
        <Table.Head scope="col" class="px-4"><span class="sr-only">{m.actions()}</span></Table.Head>
      </Table.Row>
    </Table.Header>
    <Table.Body>
      {#each requests as item (item.id)}
        <Table.Row class="hover:bg-transparent">
          <th scope="row" class="px-4 py-3 text-left align-top font-normal">
            <span class="block font-medium break-words">{item.name}</span>
            <span class="text-secondary mt-1 flex flex-col gap-1 text-sm lg:hidden">
              <span class="break-words md:hidden">{item.space_name ?? "–"}</span>
              {#if item.activation_requested_at}
                <span>
                  <TimedText
                    message={requestedMessage(item)}
                    value={item.activation_requested_at}
                  />
                </span>
              {/if}
              <span class="text-primary">{@render status(item)}</span>
            </span>
          </th>
          <Table.Cell class="hidden px-4 py-3 align-top whitespace-normal md:table-cell">
            {#if item.space_name}
              <!-- eslint-disable svelte/no-navigation-without-resolve -- localized href built from a typed id -->
              <a
                class="text-accent-stronger break-words underline underline-offset-2"
                href={localizeHref(`/admin/spaces/${item.space_id}`)}>{item.space_name}</a
              >
              <!-- eslint-enable svelte/no-navigation-without-resolve -->
            {:else}
              –
            {/if}
          </Table.Cell>
          <Table.Cell class="hidden px-4 py-3 align-top whitespace-normal lg:table-cell">
            {#if item.activation_requested_at}
              <TimedText message={requestedMessage(item)} value={item.activation_requested_at} />
            {/if}
          </Table.Cell>
          <Table.Cell class="hidden px-4 py-3 align-top whitespace-normal lg:table-cell">
            {@render status(item)}
          </Table.Cell>
          <Table.Cell class="px-4 py-3 text-right align-top">
            <!-- eslint-disable svelte/no-navigation-without-resolve -- localized href built from a typed id -->
            <a
              class="text-accent-stronger inline-flex min-h-6 items-center gap-1 font-medium underline-offset-2 hover:underline max-md:min-h-11"
              href={localizeHref(`/admin/widgets/${item.id}`)}
              aria-label={m.widget_admin_overview_review_named({ name: item.name })}
            >
              {m.widget_admin_overview_review()}
              <ArrowRight class="size-4" aria-hidden="true" />
            </a>
            <!-- eslint-enable svelte/no-navigation-without-resolve -->
          </Table.Cell>
        </Table.Row>
      {/each}
    </Table.Body>
  </Table.Root>
</div>
