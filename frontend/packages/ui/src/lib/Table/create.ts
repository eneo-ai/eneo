/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { getContext, setContext } from "svelte";
import {
  BodyRow,
  Column,
  Table,
  createTable,
  type DataLabel,
  type TableViewModel
} from "svelte-headless-table";
import {
  addPagination,
  addSelectedRows,
  addSortBy,
  addTableFilter,
  type NewTablePropSet,
  type PaginationState,
  type SelectedRowsPropSet,
  type SelectedRowsState,
  type SortByColumnOptions,
  type SortByPropSet,
  type SortByState,
  type TableFilterColumnOptions,
  type TableFilterPropSet,
  type TableFilterState,
  type TablePlugin
} from "svelte-headless-table/plugins";
import { writable, type Readable, type Writable } from "svelte/store";

type TableContext<T> = {
  displayType: Writable<"cards" | "list">;
  viewModel: ResourceTableViewModel<T>;
  gapX: string | number;
  gapY: string | number;
  layout: "flex" | "grid";
};

const contextKey = Symbol("tableContext");

export function setTableContext<T>(data: TableContext<T>) {
  setContext(contextKey, data);
}
export function getTableContext<T>(): TableContext<T> {
  return getContext(contextKey);
}

export interface CreateTableOptions {
  disableClientFilter?: boolean;
  serverSideFilter?: boolean;  // Keep filter UI but make it trigger server-side search
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
  const plugins: any = {
    select: addSelectedRows(),
    sort: addSortBy({ disableMultiSort: true }),
    page: addPagination({ initialPageSize: pageSize })
  };

  // Handle filtering based on options
  if (!options.disableClientFilter) {
    if (options.serverSideFilter) {
      // Keep filter UI but disable client-side filtering (always returns true)
      // Component will watch filterValue and trigger server-side search
      plugins.tableFilter = addTableFilter({
        fn: () => true  // No-op: all rows pass filter (server does filtering)
      });
    } else {
      // Standard client-side filtering
      plugins.tableFilter = addTableFilter({
        fn: ({ filterValue, value }) => {
          return value.toLowerCase().includes(filterValue.toLowerCase());
        }
      });
    }
  }

  const table: Table<Resource, Plugins<Resource>> = createTable(data, plugins);

  return {
    column: table.column,
    columnPrimary({
      header,
      value,
      cell,
      sortable
    }: {
      header?: string;
      /** If the Resource does not have a name field */
      value: (item: Resource) => string;
      cell: DataLabel<Resource, Plugins<Resource>, Resource>;
      sortable?: boolean;
    }) {
      const sort =
        sortable === false
          ? {
              disable: true
            }
          : {
              getSortValue(item: Resource) {
                return value(item).toLowerCase();
              }
            };
      return table.column({
        accessor: (item: Resource) => item,
        id: "table-primary-key",
        header: header ?? "",
        cell,
        plugins: {
          tableFilter: {
            getFilterValue(item) {
              return value(item).toLowerCase();
            }
          },
          sort
        }
      });
    },
    columnActions({
      header,
      cell
    }: {
      header?: "string";
      cell: DataLabel<Resource, Plugins<Resource>, Resource>;
    }) {
      return table.column({
        accessor: (item: Resource) => item,
        id: "table-action-key",
        header: header ?? "",
        cell,
        plugins: {
          tableFilter: {
            exclude: true
          },
          sort: {
            disable: true
          }
        }
      });
    },
    columnCard({
      value,
      cell
    }: {
      header?: string;
      /** If the Resource does not have a name field */
      value: (item: Resource) => string;
      cell: DataLabel<Resource, Plugins<Resource>, Resource>;
    }) {
      return table.column({
        accessor: (item: Resource) => item,
        id: "table-card-key",
        header: "",
        cell,
        plugins: {
          tableFilter: {
            getFilterValue(item) {
              return value(item).toLowerCase();
            }
          },
          sort: {
            disable: true
          }
        }
      });
    },
    createViewModel(columns: Column<Resource, Plugins<Resource>>[]) {
      const dataCols = table.createColumns(columns);
      return table.createViewModel(dataCols, {
        rowDataId: (item) => String((item as any).id)
      });
    }
  };
}

export function getCardCell<T>(row: BodyRow<T, Plugins<T>>) {
  if (row) {
    return row.cells.find((cell) => {
      return cell.id === "table-card-key";
    });
  }
  return undefined;
}

type Plugins<T> = {
  select: TablePlugin<T, SelectedRowsState<T>, Record<string, never>, SelectedRowsPropSet>;
  tableFilter: TablePlugin<T, TableFilterState<T>, TableFilterColumnOptions<T>, TableFilterPropSet>;
  sort: TablePlugin<T, SortByState<T>, SortByColumnOptions, SortByPropSet>;
  page: TablePlugin<T, PaginationState, Record<string, never>, NewTablePropSet<never>>;
};

export type ResourceTableViewModel<T> = TableViewModel<T, Plugins<T>>;
