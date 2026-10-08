/// <reference lib="dom" />
/**
 * The view query_table brings (an MCP App): the rows of the query as a table the reader can
 * sort, filter, copy and read on from.
 *
 * It takes room only when it has rows to show. A query that returned a single row, a query
 * plan, a failure, or a result delivered as a file has nothing for it, and it stays out of
 * the way. It calls query_table itself only when the reader asks for more.
 */
import { useCallback, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Icon } from "@astryxdesign/core/Icon";
import { Table, useTableSortable, type TableSortState } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { Toolbar } from "@astryxdesign/core/Toolbar";
import {
  TableRows,
  ViewFrame,
  columnWidth,
  pick,
  useHost,
  type ToolResult,
} from "../../../views/kit";
import { filterRows, pageSql, showsTable, sortRows, toTsv } from "./paging";
import "./view.css";

/** Rows drawn at once; a longer result is read on from with the button. */
const MAX_DRAWN_ROWS = 2000;

type QueryArguments = {
  file?: unknown;
  files?: unknown;
  sql?: unknown;
  explain?: unknown;
  display?: "table" | "none";
};
type QueryResult = {
  display?: "table" | "none";
  columns: string[];
  rows: unknown[][];
  truncated: boolean;
  rejected_rows?: number;
  calculation_warnings?: Array<{
    filename: string; sheet: string; formula_cells: number; missing_cached_results: number;
  }>;
  export?: unknown;
};
type Row = Record<string, unknown>;

const TEXTS = {
  sv: {
    label: "Tabell",
    rows: (n: number) => (n === 1 ? "1 rad" : `${n} rader`),
    firstRows: (n: number) => `De första ${n} raderna`,
    matching: (n: number, of: number) => `${n} av ${of} rader`,
    more: "Visa fler rader",
    loading: "Hämtar rader…",
    filter: "Filtrera rader",
    filterLoaded: "Filtret söker bland raderna som visas.",
    noMatches: "Inga rader matchar filtret.",
    clear: "Rensa filter",
    copy: "Kopiera",
    copied: "Kopierat",
    rejected: (n: number) =>
      n === 1
        ? "1 rad i filen kunde inte läsas och ingår inte."
        : `${n} rader i filen kunde inte läsas och ingår inte.`,
    calculation: (file: string, sheet: string, missing: number) =>
      `${file} · ${sheet}: Formlerna har inte räknats om. Sparade resultat kan vara inaktuella.${missing ? ` ${missing} formelceller saknar sparade resultat och behandlas som tomma värden.` : ""}`,
    failed: "Raderna kunde inte hämtas.",
    retry: "Försök igen",
  },
  en: {
    label: "Table",
    rows: (n: number) => (n === 1 ? "1 row" : `${n} rows`),
    firstRows: (n: number) => `The first ${n} rows`,
    matching: (n: number, of: number) => `${n} of ${of} rows`,
    more: "Show more rows",
    loading: "Fetching rows…",
    filter: "Filter rows",
    filterLoaded: "The filter searches the rows shown.",
    noMatches: "No rows match the filter.",
    clear: "Clear filter",
    copy: "Copy",
    copied: "Copied",
    rejected: (n: number) =>
      n === 1
        ? "1 row in the file could not be read and is not included."
        : `${n} rows in the file could not be read and are not included.`,
    calculation: (file: string, sheet: string, missing: number) =>
      `${file} · ${sheet}: Formulas were not recalculated. Saved results may be outdated.${missing ? ` ${missing} formula cells have no saved result and are treated as empty values.` : ""}`,
    failed: "The rows could not be fetched.",
    retry: "Try again",
  },
};

function queryResult(result: ToolResult): QueryResult | undefined {
  let value: unknown = result.structuredContent;
  if (!value) {
    try {
      value = JSON.parse(result.content?.find((block) => block.type === "text")?.text ?? "");
    } catch {
      return undefined;
    }
  }
  const candidate = value as Partial<QueryResult> | null;
  if (!candidate || !Array.isArray(candidate.columns) || !Array.isArray(candidate.rows))
    return undefined;
  return candidate as QueryResult;
}

/** A whole number too large for a JSON number arrives as its digits. */
const isNumeric = (value: unknown) =>
  typeof value === "number" || (typeof value === "string" && /^-?\d+$/.test(value));

function QueryResultView() {
  const args = useRef<QueryArguments | undefined>(undefined);
  const [columns, setColumns] = useState<string[]>([]);
  const [rows, setRows] = useState<unknown[][]>([]);
  /** Whether the query has rows beyond the ones held. */
  const [hasMore, setHasMore] = useState(false);
  /** Rows one fetch brings: what the first result held when it was cut short. */
  const pageSize = useRef(500);
  const [rejected, setRejected] = useState(0);
  const [calculation, setCalculation] = useState<NonNullable<QueryResult["calculation_warnings"]>>([]);
  const [sort, setSort] = useState<TableSortState>([]);
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [shown, setShown] = useState(false);
  const [copied, setCopied] = useState(false);

  const host = useHost("eneo-query-result", {
    onInput: (input) => {
      args.current = input as QueryArguments;
    },
    onResult: (result) => {
      const found = result.isError ? undefined : queryResult(result);
      // A plan, a failure, a file or a single row leaves nothing for a table to add.
      if (
        !found ||
        !showsTable({
          rows: found.rows,
          display: found.display ?? args.current?.display,
          plan: args.current?.explain === true,
          exported: Boolean(found.export),
        })
      )
        return;
      setColumns(found.columns.map(String));
      setRows(found.rows);
      setHasMore(found.truncated === true);
      if (found.truncated === true) pageSize.current = found.rows.length;
      setRejected(typeof found.rejected_rows === "number" ? found.rejected_rows : 0);
      setCalculation(found.calculation_warnings ?? []);
      setShown(true);
    },
  });
  const { app, context } = host;
  const text = pick(context, TEXTS);

  /** Another page of the query, read through the host like any call of the tool. */
  const read = useCallback(
    async (offset: number, order: TableSortState, held: unknown[][]) => {
      const query = args.current;
      if (busy || typeof query?.sql !== "string") return;
      setBusy(true);
      setFailed(false);
      try {
        const first = order[0];
        const result = await app.callServerTool({
          name: "query_table",
          arguments: {
            file: query.file,
            ...(query.files ? { files: query.files } : {}),
            // One row more than a page tells whether another page follows.
            sql: pageSql(query.sql, {
              limit: pageSize.current + 1,
              offset,
              ...(first
                ? { order: { column: first.sortKey, descending: first.direction === "descending" } }
                : {}),
            }),
          },
        });
        const found = result.isError ? undefined : queryResult(result as ToolResult);
        if (!found) throw new Error("No rows");
        setHasMore(found.truncated === true || found.rows.length > pageSize.current);
        const page = found.rows.slice(0, pageSize.current);
        setRows(offset === 0 ? page : [...held, ...page]);
      } catch {
        setFailed(true);
      } finally {
        setBusy(false);
      }
    },
    [app, busy],
  );

  const sortPlugin = useTableSortable<Row>({
    sort,
    onSortChange: (next) => {
      setSort(next);
      const first = next[0];
      if (!first) return;
      // Only part of the result is here, so the query itself is asked for the order.
      if (hasMore) void read(0, next, rows);
      else
        setRows(sortRows(rows, columns.indexOf(first.sortKey), first.direction === "descending"));
    },
  });

  const format = useMemo(
    () =>
      new Intl.NumberFormat(context.locale ?? "sv", {
        useGrouping: false,
        maximumFractionDigits: 6,
      }),
    [context.locale],
  );
  const filtering = filter.trim() !== "";
  const visible = useMemo(() => filterRows(rows, filter).slice(0, MAX_DRAWN_ROWS), [rows, filter]);
  // A row is keyed by where its column stands, so two columns of one name stay apart.
  const data = useMemo<Row[]>(
    () => visible.map((row, index) => ({ ...row, id: index }) as unknown as Row),
    [visible],
  );
  const tableColumns = useMemo(() => {
    const shown = (value: unknown) =>
      typeof value === "number"
        ? format.format(value)
        : typeof value === "object"
          ? JSON.stringify(value)
          : String(value);
    return columns.map((column, index) => {
      // A heading stands over its numbers.
      const first = visible.find((row) => row[index] !== null && row[index] !== undefined);
      return {
        key: column,
        header: column,
        sortable: true,
        align: first && isNumeric(first[index]) ? ("end" as const) : ("start" as const),
        width: columnWidth(
          column,
          visible.map((row) => shown(row[index] ?? "")),
        ),
        renderCell: (item: Row) => {
          const value = item[index];
          if (value === null || value === undefined) return <Text color="disabled">–</Text>;
          return shown(value);
        },
      };
    });
  }, [columns, visible, format]);

  const copy = async () => {
    const tsv = toTsv(columns, visible);
    try {
      await navigator.clipboard.writeText(tsv);
    } catch {
      // A frame without clipboard permission still has the old way.
      const area = Object.assign(document.createElement("textarea"), { value: tsv });
      document.body.append(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const note = filtering && hasMore ? text.filterLoaded : undefined;
  return (
    <ViewFrame
      host={host}
      name="query-result"
      shown={shown}
      label={text.label}
      title={
        filtering
          ? text.matching(visible.length, rows.length)
          : hasMore
            ? text.firstRows(rows.length)
            : text.rows(rows.length)
      }
      controls={
        <>
          <TextInput
            label={text.filter}
            isLabelHidden
            placeholder={text.filter}
            startIcon="search"
            hasClear
            value={filter}
            onChange={setFilter}
            width={208}
          />
          <Button
            variant="ghost"
            label={copied ? text.copied : text.copy}
            icon={<Icon icon={copied ? "check" : "copy"} />}
            onClick={copy}
          />
        </>
      }
      notices={
        <>
          {calculation.map((warning, index) => (
            <Banner key={index} status="warning" container="section"
              title={text.calculation(warning.filename, warning.sheet, warning.missing_cached_results)} />
          ))}
          {rejected > 0 && (
            <Banner status="warning" container="section" title={text.rejected(rejected)} />
          )}
          {failed && (
            <Banner
              status="error"
              container="section"
              title={text.failed}
              endContent={
                <Button
                  variant="ghost"
                  size="sm"
                  label={text.retry}
                  onClick={() => void read(rows.length, sort, rows)}
                />
              }
            />
          )}
        </>
      }
      footer={
        (hasMore || busy) && (
          <Toolbar
            label={text.more}
            dividers={["top"]}
            startContent={
              note ? (
                <Text type="supporting" color="secondary">
                  {note}
                </Text>
              ) : undefined
            }
            endContent={
              <Button
                variant="secondary"
                label={busy ? text.loading : text.more}
                isLoading={busy}
                onClick={() => void read(rows.length, sort, rows)}
              />
            }
          />
        )
      }
    >
      <Table<Row>
        data={data}
        columns={tableColumns}
        idKey="id"
        density="compact"
        dividers="rows"
        hasHover
        plugins={{ sort: sortPlugin }}
        scrollWrapper={TableRows}
        emptyState={
          <EmptyState
            isCompact
            title={text.noMatches}
            description={note}
            actions={<Button variant="secondary" label={text.clear} onClick={() => setFilter("")} />}
          />
        }
      />
    </ViewFrame>
  );
}

createRoot(document.getElementById("app")!).render(<QueryResultView />);
