<script lang="ts">
  import { Table } from "@intric/ui";
  import { createRender } from "svelte-headless-table";
  import HistoryActions from "./HistoryActions.svelte";
  import dayjs from "dayjs";
  import relativeTime from "dayjs/plugin/relativeTime";
  import utc from "dayjs/plugin/utc";
  dayjs.extend(relativeTime);
  dayjs.extend(utc);

  import type { Conversation, ConversationSparse } from "@intric/intric-js";
  import { getChatService } from "../../ChatService.svelte";
  import { toStore } from "svelte/store";
  import { m } from "$lib/paraglide/messages";

  // Fallback navigation (same idea as +page.svelte)
  import { pushState } from "$app/navigation";
  import { page } from "$app/state";
  import { getChatQueryParams } from "$lib/features/chat/getChatQueryParams.js";

  type Props = {
    onConversationLoaded?: ((session: Conversation) => void) | undefined;
    onConversationDeleted?: ((session: ConversationSparse) => void) | undefined;
  };

  let { onConversationLoaded, onConversationDeleted }: Props = $props();

  const chat = getChatService();
  const table = Table.createWithStore(toStore(() => chat.loadedConversations));

  function getSpaceIdFromPath(pathname: string): string {
    // /spaces/{spaceId}/chat/...
    const parts = pathname.split("/");
    return parts[2] ?? "";
  }

  const viewModel = table.createViewModel([
    table.columnPrimary({
      header: m.name(),
      value: (item) => item.name ?? "",
      cell: (item) => {
        return createRender(Table.ButtonCell, {
          label: item.value.name ?? m.untitled(),
          onclick: async () => {
            const loaded = await chat.loadConversation(item.value);
            if (!loaded) return;

            // Let parent handle UI state if provided
            onConversationLoaded?.(loaded);

            // Fallback: ensure URL/tab is updated to chat for this conversation
            const params = new URLSearchParams(
              getChatQueryParams({ chatPartner: chat.partner, conversation: loaded })
            );
            params.set("tab", "chat");

            const spaceId = getSpaceIdFromPath(page.url.pathname);
            pushState(`/spaces/${spaceId}/chat/?${params.toString()}`, {
              conversation: loaded,
              tab: "chat"
            });
          }
        });
      },
      sortable: false
    }),
    table.column({
      header: m.created(),
      accessor: "created_at",
      cell: (item) => {
        return createRender(Table.FormattedCell, {
          value: dayjs(item.value).format("YYYY-MM-DD HH:mm"),
          monospaced: true
        });
      }
    }),
    table.columnActions({
      cell: (item) => {
        return createRender(HistoryActions, {
          conversation: item.value,
          onConversationDeleted
        });
      }
    })
  ]);
</script>

<Table.Root
  {viewModel}
  resourceName={m.resource_sessions()}
  emptyMessage={m.no_previous_sessions_found()}
></Table.Root>
