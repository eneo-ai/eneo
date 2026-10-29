"use client";

import { Button } from "@astryxdesign/core/Button";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import {
  proportional,
  TableSelectionToolbar,
  useTableRowIndex,
  useTableSelection,
  type TableColumn,
  type TablePlugin,
  type TableSelectionState
} from "@astryxdesign/core/Table";
import { TextQuote } from "lucide-react";
import { useLocale, useTranslations } from "use-intl";
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Table } from "@/components/astryx/table";
import type { PreviewCell, PreviewSheet } from "./load-preview";
import type { PreviewPassage } from "./preview-kind";
import {
  columnName,
  parseTableLocator,
  tableLocator,
  toggleTableRows,
  type TableSelection
} from "./table-reference";

/** A body row of the sheet: its spreadsheet row number and each cell, formatted, under `c<column>`. */
type SheetRow = { id: string; row: number } & Record<string, string | number>;

const EMPTY_SHEET: PreviewSheet = { name: "", rows: [], totalRows: 0 };
const NUMERIC_TEXT = /^-?\d+([.,]\d+)?$/;
const isNumeric = (value: PreviewCell | undefined) =>
  typeof value === "number" || (typeof value === "string" && NUMERIC_TEXT.test(value));
const cellKey = (column: number) => `c${column}`;
const columnOf = (key: string) => (/^c\d+$/.test(key) ? Number(key.slice(1)) : null);

// Spreadsheet dates carry no time zone; the reader delivers them as UTC.
// "sv-SE" writes YYYY-MM-DD, the date format of every table in the app.
const DATE_FORMAT = new Intl.DateTimeFormat("sv-SE", { timeZone: "UTC" });
const DATE_TIME_FORMAT = new Intl.DateTimeFormat("sv-SE", {
  timeZone: "UTC",
  dateStyle: "short",
  timeStyle: "short"
});

function useCellFormat(): (value: PreviewCell | undefined) => string {
  const locale = useLocale();
  return useMemo(() => {
    // Plain digits with the decimal sign of the UI language: grouping would
    // turn a year or an id into "2 026".
    const numbers = new Intl.NumberFormat(locale, {
      useGrouping: false,
      maximumFractionDigits: 10
    });
    return (value) => {
      if (value === null || value === undefined) return "";
      if (typeof value === "number") return numbers.format(value);
      if (typeof value === "boolean") return value ? "TRUE" : "FALSE";
      if (value instanceof Date) {
        const hasTime = value.getTime() % 86_400_000 !== 0;
        return (hasTime ? DATE_TIME_FORMAT : DATE_FORMAT).format(value);
      }
      return value;
    };
  }, [locale]);
}

/** Whether a table location can be shown: its sheet, rows and column are in the preview. */
function isAvailable(target: TableSelection | null, sheets: PreviewSheet[]): boolean {
  if (!target) return true;
  const source = sheets.find((candidate) => candidate.name === target.sheet);
  return (
    !!source &&
    (target.rows ?? [target.row]).every((row) => !!source.rows[row - 1]) &&
    (target.column === null || target.column < Math.max(...source.rows.map((row) => row.length)))
  );
}

/** The rows a location selects; a single cell is marked by its highlight instead. */
function rowsOf(target: TableSelection | null, available: boolean): Set<string> {
  if (!target || !available || target.column !== null) return new Set();
  return new Set((target.rows ?? [target.row]).map(String));
}

const sheetIndex = (sheets: PreviewSheet[], name: string | null) =>
  Math.max(
    0,
    sheets.findIndex((candidate) => candidate.name === name)
  );

/**
 * Marks the rendered table the way the selection helpers read it
 * (selection.ts): the sheet on the table, the spreadsheet row number on every
 * row (the header is row 1) and the column on every cell of the file. The row
 * number and checkbox columns are the preview's chrome, unselectable, so a
 * text selection and a passage search never take them in.
 */
function anchorPlugin(sheetName: string): TablePlugin<SheetRow> {
  return {
    transformTable: (props) => ({
      ...props,
      htmlProps: { ...props.htmlProps, "data-sheet": sheetName } as typeof props.htmlProps
    }),
    transformHeaderRow: (props) => ({
      ...props,
      htmlProps: { ...props.htmlProps, "data-row": "1" } as typeof props.htmlProps
    }),
    transformHeaderCell: (props, column) => {
      const index = columnOf(column.key);
      return index === null
        ? { ...props, htmlProps: { ...props.htmlProps, className: "select-none" } }
        : {
            ...props,
            htmlProps: { ...props.htmlProps, "data-column": index } as typeof props.htmlProps
          };
    },
    transformBodyRow: (props, item) => ({
      ...props,
      htmlProps: { ...props.htmlProps, "data-row": item.row } as typeof props.htmlProps
    }),
    transformBodyCell: (props, column) => {
      const index = columnOf(column.key);
      return index === null
        ? { ...props, htmlProps: { ...props.htmlProps, className: "select-none" } }
        : {
            ...props,
            htmlProps: { ...props.htmlProps, "data-column": index } as typeof props.htmlProps
          };
    }
  };
}

type TablePreviewProps = {
  sheets: PreviewSheet[];
  /** Names the table when its sheet has no name (a CSV file). */
  title: string;
  /** A sheet to bring forward, as when a passage on it is to be shown. */
  sheet?: string | null;
  highlight?: PreviewPassage | null;
  onQuote: (text: string, locator: string | null) => void;
};

/**
 * A spreadsheet or delimited file as a table, one sheet at a time. Rows are
 * selected with their checkboxes (Shift extends from the last row picked) and
 * asked about as a row reference, without copying their values; text selected
 * inside cells is quoted by the preview around it, with its row as locator.
 */
export function TablePreview({
  sheets,
  title,
  sheet: wanted = null,
  highlight = null,
  onQuote
}: TablePreviewProps) {
  const t = useTranslations();
  const format = useCellFormat();
  const panelId = useId();
  const target = parseTableLocator(highlight?.locator);
  const targetAvailable = isAvailable(target, sheets);

  const [activeIndex, setActiveIndex] = useState(() => sheetIndex(sheets, wanted));
  const [selectedKeys, setSelectedKeys] = useState(() => rowsOf(target, targetAvailable));
  const [anchor, setAnchor] = useState<number | null>(null);

  // A new passage to show brings its sheet forward and selects its rows.
  const locator = highlight?.locator ?? null;
  const [shown, setShown] = useState({ locator, wanted });
  if (shown.locator !== locator || shown.wanted !== wanted) {
    setShown({ locator, wanted });
    if (shown.wanted !== wanted && sheets.some((candidate) => candidate.name === wanted)) {
      setActiveIndex(sheetIndex(sheets, wanted));
    }
    if (shown.locator !== locator) {
      setSelectedKeys(rowsOf(target, targetAvailable));
      setAnchor(null);
    }
  }

  const sheet = sheets[Math.min(activeIndex, sheets.length - 1)] ?? EMPTY_SHEET;
  const columnCount = sheet.rows.reduce((widest, row) => Math.max(widest, row.length), 0);

  const body = useMemo(
    () =>
      sheet.rows.slice(1).map((cells, index) => {
        const item: SheetRow = { id: String(index + 2), row: index + 2 };
        for (let column = 0; column < columnCount; column++) {
          item[cellKey(column)] = format(cells[column]);
        }
        return item;
      }),
    [sheet, columnCount, format]
  );

  const columns = useMemo((): TableColumn<SheetRow>[] => {
    const header = sheet.rows[0] ?? [];
    return Array.from({ length: columnCount }, (_, column) => ({
      key: cellKey(column),
      // A column without a heading is named by its letter, as in a spreadsheet.
      header: format(header[column]) || columnName(column),
      width: proportional(1),
      align: isNumeric(sheet.rows[1]?.[column]) ? "end" : "start"
    }));
  }, [columnCount, sheet, format]);

  const selectedRows = useMemo(
    () => [...selectedKeys].map(Number).sort((a, b) => a - b),
    [selectedKeys]
  );

  function clearSelection() {
    setSelectedKeys(new Set());
    setAnchor(null);
    window.getSelection()?.removeAllRanges();
    // A sent quote may also have a browser text highlight.
    globalThis.CSS?.highlights?.delete("file-preview-quote");
  }

  // Whether the press that toggles a row held Shift (the selection plugin
  // reports the toggle without its event), and Escape, which drops the
  // selection while there is one.
  const container = useRef<HTMLDivElement>(null);
  const extend = useRef(false);
  const clear = useRef(clearSelection);
  const hasSelection = useRef(false);
  useLayoutEffect(() => {
    clear.current = clearSelection;
    hasSelection.current = selectedKeys.size > 0;
  });
  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const record = (event: MouseEvent) => (extend.current = event.shiftKey);
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || !hasSelection.current) return;
      event.preventDefault();
      event.stopPropagation();
      clear.current();
    };
    element.addEventListener("click", record, true);
    element.addEventListener("keydown", escape);
    return () => {
      element.removeEventListener("click", record, true);
      element.removeEventListener("keydown", escape);
    };
  }, []);

  const selection = useTableSelection<SheetRow>({
    getIsItemSelected: (item) => selectedKeys.has(item.id),
    onSelectItem: ({ item }) => {
      window.getSelection()?.removeAllRanges();
      const rows = toggleTableRows(selectedRows, item.row, anchor, extend.current);
      if (!extend.current || anchor === null) setAnchor(item.row);
      setSelectedKeys(new Set(rows.map(String)));
    },
    onSelectAll: ({ isAllSelected }) => {
      setAnchor(null);
      setSelectedKeys(new Set(isAllSelected ? body.map((item) => item.id) : []));
    },
    getIsAllSelected: () => body.length > 0 && selectedKeys.size === body.length,
    getIsIndeterminate: () => selectedKeys.size > 0 && selectedKeys.size < body.length,
    getRowLabel: (item) => t("workspace_preview_row_label", { row: item.row })
  });
  const rowIndex = useTableRowIndex<SheetRow>({
    data: body,
    getRowKey: (item) => item.id,
    startFrom: 2
  });
  const anchors = useMemo(() => anchorPlugin(sheet.name), [sheet.name]);
  const plugins = useMemo(() => ({ selection, rowIndex, anchors }), [selection, rowIndex, anchors]);

  const selectionState: TableSelectionState = {
    selectedKeys,
    selectedCount: selectedKeys.size,
    hasSelection: selectedKeys.size > 0,
    clearSelection
  };
  const selectedLabel = (count: number) =>
    [sheet.name, t("table_reference_rows_selected", { count })].filter(Boolean).join(" · ");

  function quoteSelection() {
    const first = selectedRows[0];
    if (first === undefined) return;
    const rows: TableSelection = {
      sheet: sheet.name,
      row: first,
      column: null,
      rows: selectedRows
    };
    onQuote(t("table_reference_rows_selected", { count: selectedRows.length }), tableLocator(rows));
  }

  return (
    <div ref={container} className="flex min-h-0 flex-1 flex-col">
      {sheets.length > 1 && (
        <div className="border-ax-border shrink-0 border-b px-3">
          <TabList
            value={String(activeIndex)}
            onChange={(value) => {
              setActiveIndex(Number(value));
              clearSelection();
            }}
            role="tablist"
            size="sm"
            aria-label={t("file_preview_sheets")}
          >
            {sheets.map((candidate, index) => (
              <Tab key={index} value={String(index)} label={candidate.name} panelId={panelId} />
            ))}
          </TabList>
        </div>
      )}

      <div className="border-ax-border flex min-h-10 shrink-0 items-center gap-2 border-b px-3 py-1.5">
        {selectionState.hasSelection ? (
          <TableSelectionToolbar
            selection={selectionState}
            label={t("workspace_preview_selection_actions")}
            clearLabel={t("table_reference_clear")}
            renderSelectionLabel={selectedLabel}
            startContent={
              <Button
                label={t("table_reference_ask")}
                variant="primary"
                size="sm"
                icon={<TextQuote className="size-3.5" aria-hidden="true" />}
                onClick={quoteSelection}
              />
            }
          />
        ) : (
          <p className="text-ax-text-secondary text-xs">
            {targetAvailable
              ? t("workspace_preview_table_hint")
              : t("table_reference_location_unavailable")}
          </p>
        )}
      </div>

      <div
        id={panelId}
        role={sheets.length > 1 ? "tabpanel" : undefined}
        aria-label={sheets.length > 1 ? sheet.name : undefined}
        className="flex min-h-0 flex-1 flex-col"
      >
        {sheet.rows.length === 0 ? (
          <p className="text-ax-text-secondary p-6 text-sm">{t("file_preview_empty_sheet")}</p>
        ) : (
          // The table's scroll box scrolls both ways, so its header sticks.
          <div className="[&_thead]:bg-ax-surface flex min-h-0 flex-1 flex-col [&_.astryx-table-scroll-wrapper]:min-h-0 [&_.astryx-table-scroll-wrapper]:flex-1 [&_.astryx-table-scroll-wrapper]:scroll-pt-10 [&_.astryx-table-scroll-wrapper]:overflow-auto [&_thead]:sticky [&_thead]:top-0 [&_thead]:z-10">
            <Table<SheetRow>
              aria-label={sheet.name || title}
              data={body}
              columns={columns}
              idKey="id"
              density="compact"
              dividers="grid"
              textOverflow="truncate"
              plugins={plugins}
            />
          </div>
        )}
      </div>

      {sheet.totalRows === null ? (
        <p className="text-ax-text-secondary border-ax-border shrink-0 border-t px-4 py-2 text-xs">
          {t("file_preview_rows_shown", { shown: sheet.rows.length })}
        </p>
      ) : (
        sheet.totalRows > sheet.rows.length && (
          <p className="text-ax-text-secondary border-ax-border shrink-0 border-t px-4 py-2 text-xs">
            {t("file_preview_rows_shown_of_total", {
              shown: sheet.rows.length,
              total: sheet.totalRows
            })}
          </p>
        )
      )}
    </div>
  );
}
