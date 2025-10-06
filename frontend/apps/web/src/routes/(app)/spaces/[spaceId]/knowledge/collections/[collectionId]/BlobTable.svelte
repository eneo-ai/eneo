<script lang="ts">
  import type { InfoBlob } from "@intric/intric-js";
  import { Table } from "@intric/ui";
  import { createRender } from "svelte-headless-table";
  import BlobPreview from "$lib/features/knowledge/components/BlobPreview.svelte";
  import BlobActions from "./BlobActions.svelte";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import { PAGINATION } from "$lib/core/constants";
  import { m } from "$lib/paraglide/messages";

  export let blobs: InfoBlob[];
  export let canEdit: boolean;
  const table = Table.createWithResource(blobs, PAGINATION.PAGE_SIZE);

  const viewModel = table.createViewModel([
    table.columnPrimary({
      header: m.name(),
      value: (item) => item.metadata.title ?? "",
      cell: (item) => {
        return createRender(BlobPreview, {
          blob: item.value,
          isTableView: true
        });
      }
    }),

    table.column({
      header: m.size(),
      accessor: (item) => item,
      cell: (item) => formatBytes(item.value.metadata.size),
      plugins: {
        sort: { getSortValue: (item) => item.metadata.size }
      }
    }),

    table.columnActions({
      cell: (item) => {
        return createRender(BlobActions, {
          blob: item.value,
          canEdit
        });
      }
    })
  ]);

  $: table.update(blobs);
</script>

<Table.Root
  {viewModel}
  filter
  resourceName="file"
  emptyMessage={m.no_files_uploaded_yet()}
></Table.Root>
