/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { getContext, setContext } from "svelte";
import { derived, get, writable, type Readable, type Writable } from "svelte/store";
import {
  createTable,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  type AccessorFnColumnDef,
  type Header,
  type Row,
  type SortingState,
  type TableState
} from "@tanstack/table-core";
import {
  RenderComponentConfig,
  RenderSnippetConfig
} from "$lib/components/ui/data-table/render-helpers.js";

export { renderComponent, renderSnippet } from "$lib/components/ui/data-table/render-helpers.js";

/** What a header or cell function may return. */
export type CellContent =
  | RenderComponentConfig<never>
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  | RenderComponentConfig<any>
  | RenderSnippetConfig<never>
  | string
  | number
  | null
  | undefined;

export type CellArgs<Resource, Value> = { value: Value; row: Row<Resource> };

type SortOptions<Value> = {
  disable?: boolean;
  getSortValue?: (value: Value) => unknown;
  compareFn?: (a: Value, b: Value) => number;
  /** Inverts the order without changing the direction shown in the header. */
  invert?: boolean;
};

type FilterOptions<Value> = {
  exclude?: boolean;
  getFilterValue?: (value: Value) => unknown;
};

type ColumnBase<Resource, Value> = {
  header?: string | (() => CellContent);
  id?: string;
  cell?: (args: CellArgs<Resource, Value>) => CellContent;
  plugins?: { sort?: SortOptions<Value>; tableFilter?: FilterOptions<Value> };
};

export type ColumnOptions<Resource, Value> = ColumnBase<Resource, Value> & {
  accessor: keyof Resource | ((item: Resource) => Value);
};

type ColumnMeta = {
  header?: string | (() => CellContent);
  sort?: SortOptions<unknown>;
  filter?: FilterOptions<unknown>;
  cell?: (args: CellArgs<unknown, unknown>) => CellContent;
};

export type ResourceColumn<Resource> = AccessorFnColumnDef<Resource, unknown> & {
  id: string;
  meta: ColumnMeta;
};

export const PRIMARY_COLUMN_ID = "table-primary-key";
export const ACTION_COLUMN_ID = "table-action-key";
export const CARD_COLUMN_ID = "table-card-key";

export interface CreateTableOptions {
  disableClientFilter?: boolean;
  /** Keep the filter input but leave filtering to the server; watch `filterValue` to search. */
  serverSideFilter?: boolean;
}

type SortOrder = "asc" | "desc";

export type ResourceTableViewModel<Resource> = {
  columns: ResourceColumn<Resource>[];
  headers: Readable<Header<Resource, unknown>[]>;
  /** Filtered and sorted rows across all pages. */
  rows: Readable<Row<Resource>[]>;
  /** Rows of the current page. */
  pageRows: Readable<Row<Resource>[]>;
  sortOrder: (columnId: string) => Readable<SortOrder | undefined>;
  toggleSort: (columnId: string) => void;
  pluginStates: {
    sort: { sortKeys: Writable<{ id: string; order: SortOrder }[]> };
    tableFilter: { filterValue: Writable<string> };
    page: {
      pageIndex: Writable<number>;
      pageSize: Writable<number>;
      pageCount: Readable<number>;
      hasPreviousPage: Readable<boolean>;
      hasNextPage: Readable<boolean>;
    };
  };
};

function compare(a: unknown, b: unknown): number {
  if (Array.isArray(a) && Array.isArray(b)) {
    for (let i = 0; i < Math.min(a.length, b.length); i++) {
      const order = compare(a[i], b[i]);
      if (order !== 0) return order;
    }
    return 0;
  }
  if (typeof a === "number" && typeof b === "number") return a - b;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (a as any) < (b as any) ? -1 : (a as any) > (b as any) ? 1 : 0;
}

function compareValues(a: unknown, b: unknown, sort: SortOptions<unknown> | undefined): number {
  if (sort?.compareFn) return sort.compareFn(a, b);
  if (sort?.getSortValue) return compare(sort.getSortValue(a), sort.getSortValue(b));
  if (typeof a === "string" || typeof a === "number") return compare(a, b);
  if (a instanceof Date || b instanceof Date) {
    return compare(a instanceof Date ? a.getTime() : 0, b instanceof Date ? b.getTime() : 0);
  }
  return 0;
}

function textFilter(value: unknown, filterValue: string) {
  return String(value).toLowerCase().includes(filterValue.toLowerCase());
}

export function createWithResource<Resource extends Record<string, unknown>>(
  data: Resource[],
  pageSize = 999999,
  options: CreateTableOptions = {}
) {
  const resourceStore = writable(data);
  const table = createWithStore(resourceStore, pageSize, options);
  return {
    ...table,
    update(data: Resource[]) {
      resourceStore.set(data);
    }
  };
}

export function createWithStore<Resource extends Record<string, unknown>>(
  data: Readable<Resource[]>,
  pageSize = 999999,
  options: CreateTableOptions = {}
) {
  function column<Key extends keyof Resource>(
    options: ColumnBase<Resource, Resource[Key]> & { accessor: Key }
  ): ResourceColumn<Resource>;
  function column<Value>(
    options: ColumnBase<Resource, Value> & { accessor: (item: Resource) => Value }
  ): ResourceColumn<Resource>;
  function column<Value>({
    accessor,
    header,
    id,
    cell,
    plugins
  }: ColumnOptions<Resource, Value>): ResourceColumn<Resource> {
    const columnId = id ?? (typeof accessor === "string" ? accessor : header);
    if (typeof columnId !== "string") {
      throw new Error("A column needs an id, a key accessor or a string header");
    }
    const accessorFn =
      typeof accessor === "function"
        ? accessor
        : (item: Resource) => item[accessor] as unknown as Value;
    return {
      id: columnId,
      header,
      accessorFn: accessorFn as (item: Resource) => unknown,
      enableSorting: plugins?.sort?.disable !== true,
      sortUndefined: false,
      sortingFn: (a, b, columnId) =>
        compareValues(
          a.getValue(columnId),
          b.getValue(columnId),
          plugins?.sort as SortOptions<unknown>
        ),
      meta: {
        header,
        sort: plugins?.sort as SortOptions<unknown> | undefined,
        filter: plugins?.tableFilter as FilterOptions<unknown> | undefined,
        cell: cell as ColumnMeta["cell"]
      }
    };
  }

  function whole(value: (item: Resource) => string) {
    return (item: Resource) => value(item).toLowerCase();
  }

  return {
    column,
    columnPrimary({
      header,
      value,
      cell,
      sortable
    }: {
      header?: string;
      /** If the Resource does not have a name field */
      value: (item: Resource) => string;
      cell: (args: CellArgs<Resource, Resource>) => CellContent;
      sortable?: boolean;
    }) {
      return column({
        accessor: (item: Resource) => item,
        id: PRIMARY_COLUMN_ID,
        header: header ?? "",
        cell,
        plugins: {
          tableFilter: { getFilterValue: whole(value) },
          sort: sortable === false ? { disable: true } : { getSortValue: whole(value) }
        }
      });
    },
    columnActions({
      header,
      cell
    }: {
      header?: string;
      cell: (args: CellArgs<Resource, Resource>) => CellContent;
    }) {
      return column({
        accessor: (item: Resource) => item,
        id: ACTION_COLUMN_ID,
        header: header ?? "",
        cell,
        plugins: { tableFilter: { exclude: true }, sort: { disable: true } }
      });
    },
    columnCard({
      value,
      cell
    }: {
      header?: string;
      /** If the Resource does not have a name field */
      value: (item: Resource) => string;
      cell: (args: CellArgs<Resource, Resource>) => CellContent;
    }) {
      return column({
        accessor: (item: Resource) => item,
        id: CARD_COLUMN_ID,
        header: "",
        cell,
        plugins: { tableFilter: { getFilterValue: whole(value) }, sort: { disable: true } }
      });
    },
    createViewModel(columns: ResourceColumn<Resource>[]) {
      return createViewModel(data, columns, pageSize, options);
    }
  };
}

function createViewModel<Resource extends Record<string, unknown>>(
  data: Readable<Resource[]>,
  columns: ResourceColumn<Resource>[],
  initialPageSize: number,
  options: CreateTableOptions
): ResourceTableViewModel<Resource> {
  const sortKeys = writable<{ id: string; order: SortOrder }[]>([]);
  const filterValue = writable("");
  const pageIndex = writable(0);
  const pageSize = writable(initialPageSize);
  const clientFilter = !options.disableClientFilter && !options.serverSideFilter;
  const metaById = new Map(columns.map((column) => [column.id, column.meta]));

  const table = createTable<Resource>({
    data: [],
    columns: columns.map((definition) => ({
      ...definition,
      cell: (context) =>
        definition.meta.cell?.({ value: context.getValue(), row: context.row as Row<unknown> })
    })),
    state: {},
    onStateChange: () => {},
    renderFallbackValue: null,
    getRowId: (item) => String(item.id),
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    manualFiltering: !clientFilter,
    globalFilterFn: (row, columnId, filter: string) => {
      const getFilterValue = metaById.get(columnId)?.filter?.getFilterValue;
      const value = row.getValue(columnId);
      return textFilter(getFilterValue ? getFilterValue(value) : value, filter);
    },
    getColumnCanGlobalFilter: (column) => metaById.get(column.id)?.filter?.exclude !== true,
    enableMultiSort: false,
    sortDescFirst: false,
    autoResetPageIndex: false
  });
  const initialState: TableState = table.initialState;

  const model = derived(
    [data, sortKeys, filterValue, pageIndex, pageSize],
    ([$data, $sortKeys, $filterValue, $pageIndex, $pageSize]) => {
      const sorting: SortingState = $sortKeys.map((key) => {
        const invert = metaById.get(key.id)?.sort?.invert === true;
        return { id: key.id, desc: (key.order === "desc") !== invert };
      });
      table.setOptions((prev) => ({
        ...prev,
        data: $data,
        state: {
          ...initialState,
          sorting,
          globalFilter: $filterValue,
          pagination: { pageIndex: $pageIndex, pageSize: $pageSize }
        }
      }));
      const rows = table.getPrePaginationRowModel().rows;
      return {
        headers: table.getHeaderGroups()[0]?.headers ?? [],
        rows,
        pageRows: table.getRowModel().rows,
        pageCount: Math.max(1, Math.ceil(rows.length / $pageSize))
      };
    }
  );

  // Keep the current page inside the page count, e.g. after filtering shrinks the rows.
  const pageCount = derived<typeof model, number>(model, ($model, set) => {
    set($model.pageCount);
    if (get(pageIndex) > $model.pageCount - 1) pageIndex.set($model.pageCount - 1);
  });

  return {
    columns,
    headers: derived(model, ($model) => $model.headers),
    rows: derived(model, ($model) => $model.rows),
    pageRows: derived(model, ($model) => $model.pageRows),
    sortOrder: (columnId) =>
      derived(sortKeys, ($sortKeys) => $sortKeys.find((key) => key.id === columnId)?.order),
    toggleSort(columnId) {
      sortKeys.update(($sortKeys) => {
        const current = $sortKeys.find((key) => key.id === columnId)?.order;
        if (current === undefined) return [{ id: columnId, order: "asc" }];
        if (current === "asc") return [{ id: columnId, order: "desc" }];
        return [];
      });
    },
    pluginStates: {
      sort: { sortKeys },
      tableFilter: { filterValue },
      page: {
        pageIndex,
        pageSize,
        pageCount,
        hasPreviousPage: derived(pageIndex, ($pageIndex) => $pageIndex > 0),
        hasNextPage: derived(
          [pageIndex, pageCount],
          ([$pageIndex, $pageCount]) => $pageIndex < $pageCount - 1
        )
      }
    }
  };
}

type TableContext<Resource> = {
  displayType: Writable<"cards" | "list">;
  viewModel: ResourceTableViewModel<Resource>;
  gapX: string | number;
  gapY: string | number;
  layout: "flex" | "grid";
};

const contextKey = Symbol("resourceTable");

export function setTableContext<Resource>(context: TableContext<Resource>) {
  setContext(contextKey, context);
}

export function getTableContext<Resource>(): TableContext<Resource> {
  return getContext(contextKey);
}

export function getCardColumn<Resource>(viewModel: ResourceTableViewModel<Resource>) {
  return viewModel.columns.find((column) => column.id === CARD_COLUMN_ID);
}
