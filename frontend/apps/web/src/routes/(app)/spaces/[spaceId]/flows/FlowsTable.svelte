<script lang="ts">
  import type { FlowSparse } from "@eneo/eneo-js";
  import { IconWorkflow } from "@eneo/icons/workflow";
  import { IconChevronRight } from "@eneo/icons/chevron-right";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import * as Table from "$lib/components/ui/table/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import FlowActions from "./FlowActions.svelte";
  import { m } from "$lib/paraglide/messages";
  import { getLocale, localizeHref } from "$lib/paraglide/runtime";

  let { flows }: { flows: FlowSparse[] } = $props();

  const {
    state: { currentSpace }
  } = getSpacesManager();

  function flowPath(flow: FlowSparse): string {
    return `/spaces/${$currentSpace.routeId}/flows/${flow.id}`;
  }

  function formatUpdatedAt(value: string | null | undefined): string {
    if (!value) return "—";
    try {
      return new Date(value).toLocaleDateString(getLocale());
    } catch {
      return "—";
    }
  }

  function getVersionLabel(flow: FlowSparse): string {
    return flow.published_version != null ? `v${flow.published_version}` : m.flow_version_draft();
  }
</script>

{#if flows.length === 0}
  <div class="flex flex-col items-center justify-center gap-5 py-24 text-center">
    <div
      class="bg-secondary/30 border-default text-muted flex h-14 w-14 items-center justify-center rounded-2xl border"
      aria-hidden="true"
    >
      <IconWorkflow class="size-6" />
    </div>
    <div class="max-w-[44ch] space-y-1.5">
      <h3 class="text-primary text-lg font-semibold tracking-tight">
        {m.flow_empty_title()}
      </h3>
      <p class="text-secondary text-sm leading-relaxed">
        {m.flow_empty_description()}
      </p>
    </div>
  </div>
{:else}
  <!-- Desktop: Table -->
  <div
    class="border-default bg-primary hidden overflow-hidden rounded-xl border shadow-xs md:block"
  >
    <Table.Root class="border-separate border-spacing-0">
      <Table.Header>
        <Table.Row class="border-default hover:bg-transparent">
          <Table.Head
            class="text-muted border-default h-11 border-b px-4 text-xs font-medium tracking-wide uppercase"
          >
            {m.name()}
          </Table.Head>
          <Table.Head
            class="text-muted border-default h-11 border-b px-4 text-xs font-medium tracking-wide uppercase"
          >
            {m.version()}
          </Table.Head>
          <Table.Head
            class="text-muted border-default h-11 border-b px-4 text-xs font-medium tracking-wide uppercase"
          >
            {m.flow_last_updated()}
          </Table.Head>
          <Table.Head
            class="text-muted border-default h-11 w-[4.5rem] border-b px-4 text-right text-xs font-medium tracking-wide uppercase"
          >
            <span class="sr-only">{m.actions()}</span>
          </Table.Head>
        </Table.Row>
      </Table.Header>
      <Table.Body>
        {#each flows as flow (flow.id)}
          <Table.Row class="group border-default hover:bg-muted/40 transition-colors last:border-0">
            <Table.Cell class="border-default border-b p-0 align-middle">
              <!-- eslint-disable svelte/no-navigation-without-resolve -- localizeHref handles routing for dynamic flow paths -->
              <a
                href={localizeHref(flowPath(flow))}
                class="text-primary focus-visible:ring-ring/40 flex min-h-[3.25rem] items-center gap-3 px-4 py-3 font-medium outline-none focus-visible:ring-2 focus-visible:ring-inset"
              >
                <span
                  class="bg-secondary/60 text-secondary flex size-8 shrink-0 items-center justify-center rounded-lg"
                  aria-hidden="true"
                >
                  <IconWorkflow class="size-4" />
                </span>
                <span class="min-w-0 truncate">{flow.name}</span>
              </a>
              <!-- eslint-enable svelte/no-navigation-without-resolve -->
            </Table.Cell>
            <Table.Cell
              class="text-secondary border-default border-b px-4 py-3 align-middle tabular-nums"
            >
              {#if flow.published_version != null}
                <Badge variant="secondary" class="h-5 font-medium tabular-nums">
                  {getVersionLabel(flow)}
                </Badge>
              {:else}
                <Badge variant="outline" class="text-muted h-5 font-medium">
                  {m.flow_version_draft()}
                </Badge>
              {/if}
            </Table.Cell>
            <Table.Cell
              class="text-muted border-default border-b px-4 py-3 align-middle tabular-nums"
            >
              {formatUpdatedAt(flow.updated_at)}
            </Table.Cell>
            <Table.Cell class="border-default border-b px-2 py-2 text-right align-middle">
              <FlowActions {flow} />
            </Table.Cell>
          </Table.Row>
        {/each}
      </Table.Body>
    </Table.Root>
  </div>

  <!-- Mobile: stacked card list -->
  <ul class="flex flex-col gap-2 md:hidden" aria-label={m.resource_flows()}>
    {#each flows as flow (flow.id)}
      <li class="border-default bg-primary relative rounded-xl border shadow-xs">
        <div class="flex items-stretch">
          <!-- eslint-disable svelte/no-navigation-without-resolve -- localizeHref handles routing for dynamic flow paths -->
          <a
            href={localizeHref(flowPath(flow))}
            class="focus-visible:ring-ring/40 flex min-h-[4.25rem] flex-1 items-center gap-3 rounded-l-xl px-4 py-3 outline-none focus-visible:ring-2 focus-visible:ring-inset"
          >
            <span
              class="bg-secondary/60 text-secondary flex size-10 shrink-0 items-center justify-center rounded-lg"
              aria-hidden="true"
            >
              <IconWorkflow class="size-5" />
            </span>
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2">
                <p class="text-primary truncate font-medium">{flow.name}</p>
                <Badge
                  variant={flow.published_version != null ? "secondary" : "outline"}
                  class="h-5 shrink-0 font-medium tabular-nums"
                >
                  {getVersionLabel(flow)}
                </Badge>
              </div>
              <p class="text-muted mt-0.5 truncate text-xs tabular-nums">
                {m.flow_last_updated()}
                <span aria-hidden="true" class="mx-1">·</span>
                {formatUpdatedAt(flow.updated_at)}
              </p>
            </div>
            <IconChevronRight class="text-muted size-4 shrink-0" aria-hidden="true" />
          </a>
          <!-- eslint-enable svelte/no-navigation-without-resolve -->
          <div class="flex items-center pr-2">
            <FlowActions {flow} />
          </div>
        </div>
      </li>
    {/each}
  </ul>
{/if}
