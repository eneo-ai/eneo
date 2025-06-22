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

  type Props = {
    onConversationLoaded?: ((session: Conversation) => void) | undefined;
    onConversationDeleted?: ((session: ConversationSparse) => void) | undefined;
  };

  let { onConversationLoaded, onConversationDeleted }: Props = $props();

  const chat = getChatService();
  const table = Table.createWithStore(toStore(() => chat.loadedConversations));

  const viewModel = table.createViewModel([
    table.columnPrimary({
      header: m.name(),
      value: (item) => item.name ?? "",
      cell: (item) => {
        return createRender(Table.ButtonCell, {
          label: item.value.name,
          async onclick() {
            const loaded = await chat.loadConversation(item.value);
            if (loaded && onConversationLoaded) {
              onConversationLoaded(loaded);
            }
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

<Table.Root {viewModel} resourceName="session" emptyMessage={m.no_previous_sessions_found()}
></Table.Root>
