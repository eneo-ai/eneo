<script lang="ts">
  import type { IntegrationKnowledge } from "@eneo/eneo-js";
  import { IconChevronRight } from "@eneo/icons/chevron-right";
  import { SvelteSet } from "svelte/reactivity";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import ButtonCell from "$lib/components/resource-table/ButtonCell.svelte";
  import { previewLinkLabel } from "$lib/features/integrations/IntegrationData";
  import { integrationDocumentsHref } from "$lib/features/integrations/integrationDocuments";
  import {
    buildIntegrationTree,
    filterIntegrationTree,
    flattenIntegrationTree
  } from "$lib/features/integrations/integrationTree";
  import { m } from "$lib/paraglide/messages";
  import IntegrationActions from "./IntegrationActions.svelte";
  import IntegrationNameCell from "./IntegrationNameCell.svelte";
  import IntegrationSyncStatusCell from "./IntegrationSyncStatusCell.svelte";

  interface Props {
    items: IntegrationKnowledge[];
    spaceRouteId: string;
    onShowSyncHistory?: ((knowledge: IntegrationKnowledge) => void) | undefined;
  }

  let { items, spaceRouteId, onShowSyncHistory }: Props = $props();

  let filterText = $state("");
  // Parents start open so the structure is visible; the set holds the ones a person closed.
  const collapsed = new SvelteSet<string>();

  let tree = $derived(buildIntegrationTree(items));
  let rows = $derived(
    flattenIntegrationTree(
      filterIntegrationTree(tree, filterText),
      (item) => !collapsed.has(item.id)
    )
  );

  function toggle(item: IntegrationKnowledge) {
    if (collapsed.has(item.id)) collapsed.delete(item.id);
    else collapsed.add(item.id);
  }
</script>

<div class="flex w-full flex-col gap-2 pt-3.5 pr-3">
  <Input
    type="search"
    bind:value={filterText}
    aria-label={m.ui_filter()}
    placeholder={m.ui_filter_items({ resourceName: m.integrations().toLowerCase() })}
    class="max-w-md"
  />

  {#if rows.length > 0}
    <Table.Root>
      <Table.Header>
        <Table.Row>
          <Table.Head>{m.name()}</Table.Head>
          <Table.Head>{m.status()}</Table.Head>
          <Table.Head>{m.link()}</Table.Head>
          <Table.Head class="w-[1%]"><span class="sr-only">{m.actions()}</span></Table.Head>
        </Table.Row>
      </Table.Header>
      <Table.Body>
        {#each rows as row (row.item.id)}
          <Table.Row>
            <Table.Cell class="max-w-[28rem]">
              <div class="flex items-center gap-1" style="padding-left: {row.depth * 1.5}rem">
                {#if row.hasChildren}
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    aria-expanded={row.expanded}
                    aria-label={row.expanded
                      ? m.sharepoint_collapse_folder_named({ name: row.item.name })
                      : m.sharepoint_expand_folder_named({ name: row.item.name })}
                    onclick={() => toggle(row.item)}
                  >
                    <IconChevronRight
                      size="sm"
                      class="transition-transform {row.expanded ? 'rotate-90' : ''}"
                    />
                  </Button>
                {:else}
                  <span class="size-6 shrink-0" aria-hidden="true"></span>
                {/if}
                <IntegrationNameCell
                  knowledge={row.item}
                  href={integrationDocumentsHref(spaceRouteId, row.item.id)}
                />
              </div>
            </Table.Cell>
            <Table.Cell class="whitespace-normal">
              <IntegrationSyncStatusCell
                knowledge={row.item}
                documentsHref={integrationDocumentsHref(spaceRouteId, row.item.id)}
                onShowSyncHistory={onShowSyncHistory
                  ? () => onShowSyncHistory(row.item)
                  : undefined}
              />
            </Table.Cell>
            <Table.Cell>
              <ButtonCell
                link={row.item.url ?? ""}
                label={previewLinkLabel(row.item.integration_type)}
                linkIsExternal
              />
            </Table.Cell>
            <Table.Cell>
              <IntegrationActions knowledgeItem={row.item} />
            </Table.Cell>
          </Table.Row>
        {/each}
      </Table.Body>
    </Table.Root>
  {:else}
    <p class="text-secondary py-8 text-center text-sm">
      {filterText.trim() === ""
        ? m.ui_no_items_configured({ resourceNamePlural: m.integrations().toLowerCase() })
        : m.no_results_found()}
    </p>
  {/if}
</div>
