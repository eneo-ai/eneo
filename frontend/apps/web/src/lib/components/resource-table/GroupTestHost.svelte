<script lang="ts">
  import * as Table from "./index.js";

  let { title, toggleLabel }: { title: string; toggleLabel?: string } = $props();

  const table = Table.createWithResource([{ id: "1", name: "Alpha" }]);
  const viewModel = table.createViewModel([
    table.columnPrimary({ header: "Name", value: (item) => item.name, cell: () => null })
  ]);
</script>

<Table.Root {viewModel} resourceName="item" displayAs="list">
  <Table.Group {title} {toggleLabel}></Table.Group>
</Table.Root>
