<script lang="ts">
  import { Table } from "@intric/ui";
  import { createRender } from "svelte-headless-table";
  import AssistantTile from "./AssistantTile.svelte";
  import AssistantActions from "./AssistantActions.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { IconAssistant } from "@intric/icons/assistant";
  import PublishingStatusChip from "$lib/features/publishing/components/PublishingStatusChip.svelte";
  import GroupChatActions from "./GroupChatActions.svelte";
  import type { AssistantSparse, GroupChatSparse } from "@intric/intric-js";
  import { getChatQueryParams } from "$lib/features/chat/getChatQueryParams";
  import { m } from "$lib/paraglide/messages";

  export let items: (GroupChatSparse | AssistantSparse)[];
  const table = Table.createWithResource(items);

  const {
    state: { currentSpace }
  } = getSpacesManager();

  const viewModel = table.createViewModel([
    table.columnPrimary({
      header: m.name(),
      value: (item) => item.name,
      cell: (item) => {
        return createRender(Table.PrimaryCell, {
          label: item.value.name,
          link: `/spaces/${$currentSpace.routeId}/chat/?${getChatQueryParams({
            chatPartner: item.value,
            tab: "chat"
          })}`,
          icon: IconAssistant
        });
      }
    }),

    // Only show status if we're not in the personal space
    ...(!$currentSpace.personal
      ? [
          table.column({
            header: m.status(),
            accessor: (item) => item,
            cell: (item) => {
              return createRender(PublishingStatusChip, {
                resource: item.value
              });
            }
          })
        ]
      : []),

    table.columnActions({
      cell: (item) => {
        if (item.value.type === "assistant") {
          return createRender(AssistantActions, {
            assistant: item.value
          });
        }

        if (item.value.type === "group-chat") {
          return createRender(GroupChatActions, {
            groupChat: item.value
          });
        }

        return createRender(Table.FormattedCell, { value: "Unknown" });
      }
    }),

    table.columnCard({
      value: (item) => item.name,
      cell: (item) => {
        return createRender(AssistantTile, {
          item: item.value
        });
      }
    })
  ]);

  $: table.update(items);

  function isPublished(status: boolean): (assistant: { published: boolean }) => boolean {
    return (assistant: { published: boolean }) => assistant.published === status;
  }
</script>

<Table.Root
  {viewModel}
  resourceName="assistant"
  displayAs="cards"
  gapX={1.5}
  gapY={1.5}
  layout="grid"
  filterPlaceholder={m.filter_assistants_placeholder()}
  listText={m.list()}
  cardsText={m.cards()}
  noItemsMessage={m.there_are_currently_no_assistants_configured()}
>
  {#if $currentSpace.hasPermission("publish", "assistant")}
    <Table.Group title={m.published()} filterFn={isPublished(true)}></Table.Group>
    <Table.Group title={m.drafts()} filterFn={isPublished(false)}></Table.Group>
  {:else}
    <Table.Group></Table.Group>
  {/if}
</Table.Root>
