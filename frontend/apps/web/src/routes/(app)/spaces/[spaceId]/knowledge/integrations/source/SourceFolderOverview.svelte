<script lang="ts">
  import type { IntegrationKnowledge } from "@eneo/eneo-js";
  import { IconLinkExternal } from "@eneo/icons/link-external";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { formatRelativeTime } from "$lib/core/formatting/dateTime";
  import { previewLinkLabel } from "$lib/features/integrations/IntegrationData";
  import SourceStateBadge from "$lib/features/integrations/components/SourceStateBadge.svelte";
  import {
    buildIntegrationTree,
    flattenIntegrationTree
  } from "$lib/features/integrations/integrationTree";
  import { safeExternalUrl } from "$lib/features/integrations/externalUrl";
  import { itemState, itemWatchState, watchStateLabel } from "$lib/features/integrations/sources";
  import type { IntegrationSyncProgress } from "$lib/features/integrations/syncProgress";
  import { m } from "$lib/paraglide/messages";
  import IntegrationActions from "../IntegrationActions.svelte";

  interface Props {
    items: IntegrationKnowledge[];
    progress: Record<string, IntegrationSyncProgress>;
    /** Folders whose queued sync no worker has reported on yet. */
    queued: ReadonlySet<string>;
    sourceName: string;
    hrefFor: (itemId: string) => string;
  }

  let { items, progress, queued, sourceName, hrefFor }: Props = $props();

  let rows = $derived(flattenIntegrationTree(buildIntegrationTree(items), () => true));
  let showWatch = $derived(items.some((item) => item.integration_type === "sharepoint"));
</script>

<h2 tabindex="-1" data-content-heading class="sr-only">{m.integration_source_folders()}</h2>
<Table.Root aria-label={m.integration_source_folders_table_label({ name: sourceName })}>
  <Table.Header>
    <Table.Row>
      <Table.Head>{m.integration_source_folder()}</Table.Head>
      <Table.Head>{m.status()}</Table.Head>
      <Table.Head class="text-right">{m.documents()}</Table.Head>
      <Table.Head>{m.integration_source_last_up_to_date()}</Table.Head>
      {#if showWatch}
        <Table.Head>{m.integration_source_stat_watch()}</Table.Head>
      {/if}
      <Table.Head class="w-[1%]"><span class="sr-only">{m.actions()}</span></Table.Head>
    </Table.Row>
  </Table.Header>
  <Table.Body>
    {#each rows as row (row.item.id)}
      {@const item = row.item}
      {@const state = itemState(item, progress, queued)}
      <Table.Row>
        <Table.Cell class="max-w-[24rem]">
          <!-- eslint-disable svelte/no-navigation-without-resolve -- href comes from the caller -->
          <a
            href={hrefFor(item.id)}
            data-sveltekit-noscroll
            data-sveltekit-replacestate
            data-sveltekit-keepfocus
            style:padding-left="{row.depth * 1.25}rem"
            class="focus-visible:ring-stronger block truncate rounded font-medium hover:underline focus-visible:ring-2 focus-visible:outline-none"
          >
            {item.name}
            {#if item.original_name && item.original_name !== item.name}
              <span class="text-secondary font-normal">({item.original_name})</span>
            {/if}
          </a>
          <!-- eslint-enable svelte/no-navigation-without-resolve -->
          {#if item.folder_path}
            <span
              class="text-secondary block truncate text-xs"
              style:padding-left="{row.depth * 1.25}rem">{item.folder_path}</span
            >
          {/if}
        </Table.Cell>
        <Table.Cell><SourceStateBadge {state} /></Table.Cell>
        <Table.Cell class="text-right tabular-nums">
          {progress[item.id] ? "–" : (item.metadata?.document_count ?? 0)}
        </Table.Cell>
        <Table.Cell class="text-secondary">
          {#if item.metadata?.last_synced_at}
            {formatRelativeTime(item.metadata.last_synced_at)}
          {:else if item.metadata?.last_sync_attempted_at}
            {m.integration_source_last_attempt_at({
              time: formatRelativeTime(item.metadata.last_sync_attempted_at)
            })}
          {:else}
            –
          {/if}
        </Table.Cell>
        {#if showWatch}
          {@const watch = itemWatchState(item)}
          <Table.Cell class={watch === "expired" ? "text-warning-stronger" : "text-secondary"}>
            {item.integration_type === "sharepoint" ? watchStateLabel(watch) : "–"}
          </Table.Cell>
        {/if}
        <Table.Cell>
          <div class="flex items-center justify-end gap-1">
            {#if safeExternalUrl(item.url)}
              <Button
                href={safeExternalUrl(item.url)}
                target="_blank"
                rel="noopener noreferrer"
                variant="ghost"
                size="icon-sm"
                aria-label={m.integration_source_open_item_link({
                  label: previewLinkLabel(item.integration_type),
                  name: item.name
                })}
              >
                <IconLinkExternal size="sm" />
              </Button>
            {/if}
            <IntegrationActions
              knowledgeItem={item}
              syncActive={state === "syncing" || state === "queued"}
            />
          </div>
        </Table.Cell>
      </Table.Row>
    {/each}
  </Table.Body>
</Table.Root>
