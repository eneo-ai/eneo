<script lang="ts">
  import { intlLocale } from "$lib/core/formatting/dateTime";
  import { m } from "$lib/paraglide/messages";
  import { Button } from "$lib/components/ui/button/index.js";
  import TextQuote from "@lucide/svelte/icons/text-quote";
  import X from "@lucide/svelte/icons/x";
  import type { PreviewPassage } from "../FilePreview.svelte";
  import {
    columnName,
    parseTableLocator,
    tableExcerpt,
    tableLocator,
    toggleTableRows,
    type TableSelection
  } from "../tableReference";
  import type { PreviewCell, PreviewSheet } from "../loadPreview";

  type Props = {
    sheets: PreviewSheet[];
    /** A sheet to bring forward, as when a passage on it is to be shown. */
    sheet?: string | null;
    highlight?: PreviewPassage | null;
    onquote: (text: string, locator: string | null) => void;
  };

  let { sheets, sheet: wanted = null, highlight = null, onquote }: Props = $props();

  let activeIndex = $state(0);
  let anchor = $state<number | null>(null);
  let focused = $state({ row: 2, column: 0 });
  const target = $derived(parseTableLocator(highlight?.locator));
  const targetAvailable = $derived.by(() => {
    if (!target) return true;
    const source = sheets.find((candidate) => candidate.name === target.sheet);
    return (
      !!source &&
      (target.rows ?? [target.row]).every((row) => !!source.rows[row - 1]) &&
      (target.column === null || target.column < Math.max(...source.rows.map((row) => row.length)))
    );
  });
  let selected = $derived<TableSelection | null>(targetAvailable ? target : null);
  const location = $derived(
    selected
      ? [
          selected.sheet,
          selected.rows
            ? m.table_reference_rows_selected({ count: selected.rows.length })
            : selected.column === null
              ? m.table_reference_row({ row: selected.row })
              : `${columnName(selected.column)}${selected.row}`
        ]
          .filter(Boolean)
          .join(" · ")
      : ""
  );
  function clearSelection() {
    selected = null;
    anchor = null;
    window.getSelection()?.removeAllRanges();
    // A sent quote may also have a browser text highlight.
    CSS.highlights?.delete("file-preview-quote");
  }
  function select(row: number, column: number, extend = false) {
    if (column < 0) {
      window.getSelection()?.removeAllRanges();
      const rows = toggleTableRows(selected?.rows ?? [], row, anchor, extend);
      if (!extend || anchor === null) anchor = row;
      selected = rows.length ? { sheet: sheet.name, row: rows[0], column: null, rows } : null;
      return;
    }
    // Leave drag-to-select/copy text intact.
    if (window.getSelection()?.toString()) return;
    anchor = null;
    selected = { sheet: sheet.name, row, column };
  }
  function rowSelected(row: number) {
    return selected?.rows?.includes(row) ?? (selected?.row === row && selected.column === null);
  }
  function navigate(event: KeyboardEvent, row: number, column: number) {
    if (event.key === "Escape") {
      clearSelection();
      event.preventDefault();
      return;
    }
    const next = { row, column };
    if (event.key === "ArrowLeft") next.column--;
    else if (event.key === "ArrowRight") next.column++;
    else if (event.key === "ArrowUp") next.row--;
    else if (event.key === "ArrowDown") next.row++;
    else if (event.key === "Home") next.column = -1;
    else if (event.key === "End") next.column = columnCount - 1;
    else return;
    event.preventDefault();
    next.column = Math.max(-1, Math.min(columnCount - 1, next.column));
    next.row = Math.max(2, Math.min(sheet.rows.length, next.row));
    focused = next;
    if (event.shiftKey && column === -1 && next.column === -1) {
      if (anchor === null) anchor = row;
      select(next.row, -1, true);
    }
    const table = (event.currentTarget as HTMLElement).closest("table");
    table
      ?.querySelector<HTMLButtonElement>(
        `button[data-select-row="${next.row}"][data-select-column="${next.column}"]`
      )
      ?.focus();
  }
  function quoteSelection() {
    if (!selected) return;
    if (selected.rows) {
      onquote(
        m.table_reference_rows_selected({ count: selected.rows.length }),
        tableLocator(selected)
      );
      return;
    }
    const text = tableExcerpt(sheet, selected, formatCell, {
      empty: m.table_reference_empty(),
      truncated: m.table_reference_truncated()
    });
    if (text) onquote(text, tableLocator(selected));
  }
  $effect(() => {
    const index = sheets.findIndex((candidate) => candidate.name === wanted);
    if (index !== -1) activeIndex = index;
  });
  const sheet = $derived(
    sheets[Math.min(activeIndex, sheets.length - 1)] ?? { name: "", rows: [], totalRows: 0 }
  );
  const columnCount = $derived(sheet.rows.reduce((widest, row) => Math.max(widest, row.length), 0));
  const columns = $derived(Array.from({ length: columnCount }, (_, index) => index));
  const header = $derived(sheet.rows[0] ?? []);
  const body = $derived(sheet.rows.slice(1));

  // Plain digits with the decimal sign of the UI language: grouping would turn
  // a year or an id into "2 026".
  const numberFormat = new Intl.NumberFormat(intlLocale(), {
    useGrouping: false,
    maximumFractionDigits: 10
  });
  // Spreadsheet dates carry no time zone; the reader delivers them as UTC.
  // "sv-SE" writes YYYY-MM-DD, the date format of every table in the app.
  const dateFormat = new Intl.DateTimeFormat("sv-SE", { timeZone: "UTC" });
  const dateTimeFormat = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "UTC",
    dateStyle: "short",
    timeStyle: "short"
  });

  function formatCell(value: PreviewCell | undefined): string {
    if (value === null || value === undefined) return "";
    if (typeof value === "number") return numberFormat.format(value);
    if (typeof value === "boolean") return value ? "TRUE" : "FALSE";
    if (value instanceof Date) {
      const hasTime = value.getTime() % 86_400_000 !== 0;
      return (hasTime ? dateTimeFormat : dateFormat).format(value);
    }
    return value;
  }

  const NUMERIC_TEXT = /^-?\d+([.,]\d+)?$/;
  const isNumeric = (value: PreviewCell | undefined) =>
    typeof value === "number" || (typeof value === "string" && NUMERIC_TEXT.test(value));
</script>

<div class="flex min-h-0 flex-1 flex-col">
  {#if sheets.length > 1}
    <div
      role="tablist"
      aria-label={m.file_preview_sheets()}
      class="border-border flex shrink-0 gap-1 overflow-x-auto border-b px-3 py-2"
    >
      {#each sheets as candidate, index (index)}
        <button
          type="button"
          role="tab"
          aria-selected={index === activeIndex}
          onclick={() => {
            activeIndex = index;
            focused = { row: 2, column: 0 };
            clearSelection();
          }}
          class="focus-visible:ring-ring rounded-md px-2.5 py-1 text-sm whitespace-nowrap transition-colors focus-visible:ring-2 focus-visible:outline-none motion-reduce:transition-none {index ===
          activeIndex
            ? 'bg-muted text-foreground font-medium'
            : 'text-muted-foreground hover:bg-muted/60 hover:text-foreground'}"
        >
          {candidate.name}
        </button>
      {/each}
    </div>
  {/if}

  <div class="border-border flex min-h-10 shrink-0 flex-wrap items-center gap-2 border-b px-3 py-2">
    <span class="text-muted-foreground min-w-0 flex-1 text-xs" role="status">
      {selected
        ? location
        : !targetAvailable
          ? m.table_reference_location_unavailable()
          : m.table_reference_hint()}
    </span>
    {#if selected}
      <Button size="sm" onclick={quoteSelection}>
        <TextQuote class="size-3.5" aria-hidden="true" />
        {m.table_reference_ask()}
      </Button>
      <button
        type="button"
        onclick={clearSelection}
        aria-label={m.table_reference_clear()}
        class="hover:bg-muted focus-visible:ring-ring rounded p-1 focus-visible:ring-2 focus-visible:outline-none"
      >
        <X class="size-4" aria-hidden="true" />
      </button>
    {/if}
  </div>

  {#if sheet.rows.length === 0}
    <p class="text-muted-foreground p-6 text-sm">{m.file_preview_empty_sheet()}</p>
  {:else}
    <div class="min-h-0 flex-1 overflow-auto">
      <!-- The sheet and row numbers are how a quote says where in a table it was taken. -->
      <table
        class="w-max min-w-full border-separate border-spacing-0 text-sm"
        data-sheet={sheet.name}
      >
        <thead>
          <tr data-row="1">
            <th
              class="bg-muted border-border sticky top-0 left-0 z-20 w-px border-r border-b px-2 py-1.5"
            ></th>
            {#each columns as column (column)}
              <th
                scope="col"
                class="bg-muted border-border text-foreground sticky top-0 z-10 max-w-[24rem] truncate border-r border-b px-3 py-1.5 font-semibold {isNumeric(
                  body[0]?.[column]
                )
                  ? 'text-right'
                  : 'text-left'}"
              >
                {formatCell(header[column])}
              </th>
            {/each}
          </tr>
        </thead>
        <tbody>
          {#each body as row, rowIndex (rowIndex)}
            <tr data-row={rowIndex + 2}>
              <!-- Numbered as in a spreadsheet, where the header is row 1. -->
              <th
                scope="row"
                class="bg-muted text-muted-foreground border-border sticky left-0 border-r border-b text-right text-xs font-normal tabular-nums select-none"
              >
                <button
                  type="button"
                  data-select-row={rowIndex + 2}
                  data-select-column={-1}
                  tabindex={focused.row === rowIndex + 2 && focused.column === -1 ? 0 : -1}
                  onfocus={() => (focused = { row: rowIndex + 2, column: -1 })}
                  onclick={(event) => select(rowIndex + 2, -1, event.shiftKey)}
                  onkeydown={(event) => navigate(event, rowIndex + 2, -1)}
                  aria-label={m.table_reference_select_row({ row: rowIndex + 2 })}
                  aria-pressed={rowSelected(rowIndex + 2)}
                  class="hover:bg-accent-dimmer focus-visible:ring-accent-default w-full px-2 py-1.5 focus-visible:ring-2 focus-visible:ring-inset focus-visible:outline-none {rowSelected(
                    rowIndex + 2
                  )
                    ? 'bg-accent-dimmer text-accent-stronger'
                    : ''}">{rowIndex + 2}</button
                >
              </th>
              {#each columns as column (column)}
                {@const text = formatCell(row[column])}
                {@const isSelected =
                  rowSelected(rowIndex + 2) ||
                  (selected?.row === rowIndex + 2 && selected.column === column)}
                <td
                  data-column={column}
                  class="border-border max-w-[24rem] border-r border-b {isSelected
                    ? 'bg-accent-dimmer'
                    : ''}"
                >
                  <button
                    type="button"
                    data-select-row={rowIndex + 2}
                    data-select-column={column}
                    tabindex={focused.row === rowIndex + 2 && focused.column === column ? 0 : -1}
                    onfocus={() => (focused = { row: rowIndex + 2, column })}
                    onclick={() => select(rowIndex + 2, column)}
                    onkeydown={(event) => navigate(event, rowIndex + 2, column)}
                    aria-label={m.table_reference_select_cell({
                      cell: `${columnName(column)}${rowIndex + 2}`,
                      heading: formatCell(header[column]),
                      value: text || m.table_reference_empty()
                    })}
                    aria-pressed={isSelected}
                    class="hover:bg-accent-dimmer focus-visible:ring-accent-default block min-h-8 w-full max-w-[24rem] truncate px-3 py-1.5 select-text focus-visible:ring-2 focus-visible:ring-inset focus-visible:outline-none {isNumeric(
                      row[column]
                    )
                      ? 'text-right tabular-nums'
                      : 'text-left'} {isSelected ? 'ring-accent-default ring-1 ring-inset' : ''}"
                    title={text.length > 40 ? text : undefined}>{text || "\u00a0"}</button
                  >
                </td>
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}

  {#if sheet.totalRows === null}
    <p class="text-muted-foreground border-border shrink-0 border-t px-4 py-2 text-xs">
      {m.file_preview_rows_shown({ shown: sheet.rows.length })}
    </p>
  {:else if sheet.totalRows > sheet.rows.length}
    <p class="text-muted-foreground border-border shrink-0 border-t px-4 py-2 text-xs">
      {m.file_preview_rows_shown_of_total({ shown: sheet.rows.length, total: sheet.totalRows })}
    </p>
  {/if}
</div>
