import { get, writable } from "svelte/store";
import { describe, expect, test } from "vitest";
import { createWithResource, createWithStore } from "./create.js";

type Item = { id: string; name: string; size: number; tags: string[] };

const items: Item[] = [
  { id: "1", name: "Beta", size: 30, tags: ["red"] },
  { id: "2", name: "alpha", size: 10, tags: ["blue"] },
  { id: "3", name: "Gamma", size: 20, tags: ["green"] }
];

function watch<T>(store: { subscribe: (run: (value: T) => void) => () => void }) {
  const unsubscribe = store.subscribe(() => {});
  return unsubscribe;
}

function names(rows: { original: Item }[]) {
  return rows.map((row) => row.original.name);
}

describe("resource table view model", () => {
  test("cycles a column through ascending, descending and unsorted", () => {
    const table = createWithResource(items);
    const view = table.createViewModel([
      table.columnPrimary({ header: "Name", value: (item) => item.name, cell: () => null })
    ]);
    const stop = watch(view.pageRows);

    expect(names(get(view.pageRows))).toEqual(["Beta", "alpha", "Gamma"]);
    view.toggleSort("table-primary-key");
    expect(names(get(view.pageRows))).toEqual(["alpha", "Beta", "Gamma"]);
    view.toggleSort("table-primary-key");
    expect(names(get(view.pageRows))).toEqual(["Gamma", "Beta", "alpha"]);
    view.toggleSort("table-primary-key");
    expect(names(get(view.pageRows))).toEqual(["Beta", "alpha", "Gamma"]);
    stop();
  });

  test("sorts by getSortValue and inverts without changing the shown order", () => {
    const table = createWithResource(items);
    const view = table.createViewModel([
      table.column({
        accessor: (item) => item,
        id: "size",
        header: "Size",
        plugins: { sort: { getSortValue: (item) => item.size, invert: true } }
      })
    ]);
    const stop = watch(view.pageRows);

    view.toggleSort("size");
    expect(get(view.sortOrder("size"))).toBe("asc");
    expect(names(get(view.pageRows))).toEqual(["Beta", "Gamma", "alpha"]);
    stop();
  });

  test("filters on getFilterValue and skips excluded columns", () => {
    const table = createWithResource(items);
    const view = table.createViewModel([
      table.column({
        accessor: "tags",
        header: "Tags",
        plugins: { tableFilter: { getFilterValue: (tags) => (tags as string[]).join(" ") } }
      }),
      table.columnActions({ cell: () => null })
    ]);
    const stop = watch(view.rows);

    view.pluginStates.tableFilter?.filterValue.set("GREEN");
    expect(names(get(view.rows))).toEqual(["Gamma"]);
    // The action column is excluded, so its object value never matches.
    view.pluginStates.tableFilter?.filterValue.set("object");
    expect(get(view.rows)).toHaveLength(0);
    stop();
  });

  test("keeps every row when the server does the filtering", () => {
    const table = createWithResource(items, 999999, { serverSideFilter: true });
    const view = table.createViewModel([table.column({ accessor: "name", header: "Name" })]);
    const stop = watch(view.rows);

    view.pluginStates.tableFilter?.filterValue.set("zzz");
    expect(get(view.rows)).toHaveLength(3);
    stop();
  });

  test("follows update() and pages the rows", () => {
    const table = createWithResource(items, 2);
    const view = table.createViewModel([table.column({ accessor: "name", header: "Name" })]);
    const stopRows = watch(view.pageRows);
    const stopCount = watch(view.pluginStates.page.pageCount);

    expect(get(view.pluginStates.page.pageCount)).toBe(2);
    view.pluginStates.page.pageIndex.set(1);
    expect(names(get(view.pageRows))).toEqual(["Gamma"]);
    table.update(items.slice(0, 1));
    expect(get(view.pluginStates.page.pageIndex)).toBe(0);
    expect(names(get(view.pageRows))).toEqual(["Beta"]);
    stopRows();
    stopCount();
  });

  test("keys rows by position, so items without or with repeated ids still render", () => {
    const table = createWithResource([{ name: "a" }, { name: "b" }, { name: "b" }] as Record<
      string,
      unknown
    >[]);
    const view = table.createViewModel([table.column({ accessor: "name", header: "Name" })]);
    const stop = watch(view.pageRows);

    const ids = get(view.pageRows).map((row) => row.id);
    expect(new Set(ids).size).toBe(3);
    stop();
  });

  test("shows the value as text when a column has no cell function", () => {
    const table = createWithResource(items);
    const view = table.createViewModel([table.column({ accessor: "size", header: "Size" })]);
    const stop = watch(view.pageRows);

    const cell = get(view.pageRows)[0].getVisibleCells()[0];
    const render = cell.column.columnDef.cell as (context: unknown) => unknown;
    expect(render(cell.getContext())).toBe("30");
    stop();
  });

  test("rebuilds rows when items are changed in place and re-emitted", () => {
    const data = writable(items.map((item) => ({ ...item })));
    const table = createWithStore(data);
    const view = table.createViewModel([table.column({ accessor: "name", header: "Name" })]);
    const stop = watch(view.pageRows);

    const before = get(view.pageRows)[0];
    data.update((current) => {
      current[0].name = "Renamed";
      return current;
    });
    const after = get(view.pageRows)[0];
    expect(after).not.toBe(before);
    expect(after.original.name).toBe("Renamed");
    stop();
  });

  test("refuses a column it cannot identify", () => {
    const table = createWithResource(items);
    expect(() => table.column({ accessor: (item) => item, header: () => null })).toThrow();
  });
});
