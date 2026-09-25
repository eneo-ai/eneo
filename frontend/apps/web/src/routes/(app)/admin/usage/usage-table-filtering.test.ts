import * as Table from "$lib/components/resource-table/index.js";
import { get } from "svelte/store";
import { expect, test } from "vitest";

test("the shared table filters all loaded records before taking ten rows", () => {
  const records = Array.from({ length: 30 }, (_, index) => ({
    id: String(index),
    name: `resource-${index}`
  }));
  const table = Table.createWithResource(records, 10);
  const view = table.createViewModel([table.column({ accessor: "name", header: "Name" })]);
  // The rendered table subscribes to both stores, including page-count clamping.
  const unsubscribeRows = view.pageRows.subscribe(() => {});
  const unsubscribeCount = view.pluginStates.page.pageCount.subscribe(() => {});
  try {
    expect(get(view.pageRows)).toHaveLength(10);
    view.pluginStates.page.pageIndex.set(2);
    view.pluginStates.tableFilter?.filterValue.set("resource-27");
    expect(get(view.rows)).toHaveLength(1);
    expect(get(view.pageRows)).toHaveLength(1);
    expect(get(view.pluginStates.page.pageIndex)).toBe(0);
  } finally {
    unsubscribeRows();
    unsubscribeCount();
  }
});
