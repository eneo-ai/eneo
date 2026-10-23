/// <reference lib="dom" />
/**
 * The view run_javascript brings (an MCP App): the returned value as a table the reader can
 * sort, filter and copy, or as a single value, a key/value list or JSON; the code, input and
 * logs behind a disclosure; and, when the input is a flat set of values, fields to change them
 * and run the same code again.
 *
 * It takes room only when the tool said the reader sees the value. A failed run is the model's
 * retry loop and a hidden intermediate step stays hidden; an exported table shows its first rows
 * as a preview, with the file holding the rest.
 * Nothing leaves the view for the conversation unless the reader quotes it.
 */
import { useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { Badge } from "@astryxdesign/core/Badge";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { CodeBlock } from "@astryxdesign/core/CodeBlock";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Icon } from "@astryxdesign/core/Icon";
import { NumberInput } from "@astryxdesign/core/NumberInput";
import { Switch } from "@astryxdesign/core/Switch";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { Table, useTableSortable, type TableSortState } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { Toolbar } from "@astryxdesign/core/Toolbar";
import {
  TableRows,
  ViewFrame,
  chevronDownIcon,
  chevronUpIcon,
  codeIcon,
  columnWidth,
  copyText,
  filterRows,
  isNumeric,
  numberFormatter,
  pick,
  playIcon,
  sortRows,
  toTsv,
  undoIcon,
  useHost,
  type ToolResult,
} from "../../../views/kit";
import {
  asTabular,
  editableInput,
  labelOf,
  showsResult,
  type DisplayMode,
  type ResultKind,
  type Scalar,
} from "../shape";
import "./view.css";

/** Rows drawn at once; the rest are added with the button. All of them are already here. */
const ROWS_PER_PAGE = 2000;

type Arguments = {
  code?: unknown;
  input?: unknown;
  display?: DisplayMode;
  title?: unknown;
  export?: unknown;
};
type Outcome = {
  ok: boolean;
  result?: unknown;
  error?: { code?: string; message?: string; line?: number };
  logs?: string[];
  dropped_log_lines?: number;
  duration_ms?: number;
  export?: { rows?: number; preview_rows?: number };
};
type Row = Record<string, unknown>;

const TEXTS = {
  sv: {
    label: "Beräkning",
    result: "Resultat",
    rows: (n: number) => (n === 1 ? "1 rad" : `${n} rader`),
    matching: (n: number, of: number) => `${n} av ${of} rader`,
    more: "Visa fler rader",
    filter: "Filtrera rader",
    noMatches: "Inga rader matchar filtret.",
    clear: "Rensa filter",
    copy: "Kopiera",
    copied: "Kopierat",
    details: "Visa kod",
    hideDetails: "Dölj kod",
    detailsLabel: "Koden bakom resultatet",
    code: "Kod",
    input: "Indata",
    logs: "Logg",
    language: "JavaScript",
    rerunNote: "Samma kod körs igen med värdena ovan. Svaret i chatten ändras inte.",
    preview: (shown: number, total: number) =>
      `Förhandsvisning: de första ${shown} av ${total} rader. Hela resultatet finns i filen.`,
    noInputTitle: "Ingen indata",
    noInput:
      "Koden fick inga värden som indata, så det finns inget att ändra här. Be om beräkningen igen med värdena som indata för att kunna räkna om.",
    dropped: (n: number) => (n === 1 ? "1 rad utelämnad" : `${n} rader utelämnade`),
    duration: (ms: number) => `Kördes på ${ms} ms`,
    rerun: "Beräkna igen",
    running: "Beräknar…",
    reset: "Återställ",
    recomputed: "Omräknat",
    failed: "Beräkningen misslyckades.",
    key: "Fält",
    value: "Värde",
    yes: "ja",
    no: "nej",
  },
  en: {
    label: "Calculation",
    result: "Result",
    rows: (n: number) => (n === 1 ? "1 row" : `${n} rows`),
    matching: (n: number, of: number) => `${n} of ${of} rows`,
    more: "Show more rows",
    filter: "Filter rows",
    noMatches: "No rows match the filter.",
    clear: "Clear filter",
    copy: "Copy",
    copied: "Copied",
    details: "Show code",
    hideDetails: "Hide code",
    detailsLabel: "The code behind the result",
    code: "Code",
    input: "Input",
    logs: "Logs",
    language: "JavaScript",
    rerunNote: "The same code runs again with the values above. The answer in the chat stays as it is.",
    preview: (shown: number, total: number) =>
      `Preview: the first ${shown} of ${total} rows. The whole result is in the file.`,
    noInputTitle: "No input",
    noInput:
      "The code was given no values as input, so there is nothing to change here. Ask for the calculation again with the values as input to be able to recalculate.",
    dropped: (n: number) => (n === 1 ? "1 line dropped" : `${n} lines dropped`),
    duration: (ms: number) => `Ran in ${ms} ms`,
    rerun: "Run again",
    running: "Running…",
    reset: "Reset",
    recomputed: "Recomputed",
    failed: "The calculation failed.",
    key: "Field",
    value: "Value",
    yes: "yes",
    no: "no",
  },
};

function outcomeOf(result: ToolResult): Outcome | undefined {
  let value: unknown = result.structuredContent;
  if (!value) {
    try {
      value = JSON.parse(result.content?.find((block) => block.type === "text")?.text ?? "");
    } catch {
      return undefined;
    }
  }
  const candidate = value as Partial<Outcome> | null;
  return candidate && typeof candidate.ok === "boolean" ? (candidate as Outcome) : undefined;
}

const isFlatObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" &&
  value !== null &&
  !Array.isArray(value) &&
  Object.values(value).every((v) => v === null || typeof v !== "object");

function ResultView() {
  const [args, setArgs] = useState<Arguments>({});
  /** The run the model made, kept so a reader can return to it after running again. */
  const [original, setOriginal] = useState<Outcome>();
  const [outcome, setOutcome] = useState<Outcome>();
  const [kind, setKind] = useState<ResultKind>(false);
  const [draft, setDraft] = useState<Record<string, Scalar>>();
  const [recomputed, setRecomputed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string>();
  const [sort, setSort] = useState<TableSortState>([]);
  const [filter, setFilter] = useState("");
  const [drawn, setDrawn] = useState(ROWS_PER_PAGE);
  const [copied, setCopied] = useState(false);
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState("code");

  const host = useHost("eneo-compute-result", {
    onInput: (input) => {
      const next = input as Arguments;
      setArgs(next);
      setDraft(editableInput(next.input));
    },
    onResult: (result) => {
      const found = result.isError ? undefined : outcomeOf(result);
      if (!found) return;
      setOriginal(found);
      setOutcome(found);
      // The same rule the tool used to tell the model what the reader sees.
      setKind(
        showsResult({
          ok: found.ok,
          result: found.result,
          exported: found.export !== undefined,
          display: (found as { display?: DisplayMode }).display ?? args.display ?? "auto",
        }),
      );
    },
  });
  const { app, context } = host;
  const text = pick(context, TEXTS);
  const shown = kind !== false && outcome !== undefined;
  const value = outcome?.result;
  const table = useMemo(() => (kind === "table" ? asTabular(value) : undefined), [kind, value]);

  const format = useMemo(() => numberFormatter(context.locale), [context.locale]);
  const shownCell = (cell: unknown) =>
    typeof cell === "number" || typeof cell === "string"
      ? format(cell)
      : typeof cell === "boolean"
        ? cell
          ? text.yes
          : text.no
        : typeof cell === "object"
          ? JSON.stringify(cell)
          : String(cell);

  // The table: every row is here, so sorting and filtering happen in the view itself.
  const columns = table?.columns ?? [];
  const ordered = useMemo(() => {
    if (!table) return [];
    const first = sort[0];
    if (!first) return table.rows;
    return sortRows(table.rows, columns.indexOf(first.sortKey), first.direction === "descending");
  }, [table, sort, columns]);
  const matching = useMemo(() => filterRows(ordered, filter), [ordered, filter]);
  const visible = useMemo(() => matching.slice(0, drawn), [matching, drawn]);
  const data = useMemo<Row[]>(
    () => visible.map((row, index) => ({ ...row, id: index }) as unknown as Row),
    [visible],
  );
  const sortPlugin = useTableSortable<Row>({ sort, onSortChange: setSort });
  const tableColumns = useMemo(
    () =>
      columns.map((column, index) => {
        const first = visible.find((row) => row[index] !== null && row[index] !== undefined);
        return {
          key: column,
          header: labelOf(column),
          sortable: true,
          align: first && isNumeric(first[index]) ? ("end" as const) : ("start" as const),
          width: columnWidth(
            column,
            visible.map((row) => shownCell(row[index] ?? "")),
          ),
          renderCell: (item: Row) => {
            const cell = item[index];
            if (cell === null || cell === undefined) return <Text color="disabled">–</Text>;
            return shownCell(cell);
          },
        };
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [columns, visible, format, text],
  );

  const copy = async () => {
    const payload = table
      ? toTsv(columns.map(labelOf), matching)
      : isFlatObject(value)
        ? toTsv(
            [text.key, text.value],
            Object.entries(value).map(([key, cell]) => [labelOf(key), cell]),
          )
        : typeof value === "object"
          ? JSON.stringify(value, null, 2)
          : String(value);
    await copyText(payload);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  /** The same code over the reader's edited input, through the host like any call of the tool. */
  const rerun = async () => {
    if (busy || typeof args.code !== "string" || !draft) return;
    setBusy(true);
    setFailure(undefined);
    try {
      const result = await app.callServerTool({
        name: "run_javascript",
        arguments: { code: args.code, input: draft, display: "none", export: false },
      });
      const found = result.isError ? undefined : outcomeOf(result as ToolResult);
      if (!found) throw new Error(text.failed);
      if (!found.ok) throw new Error(found.error?.message ?? text.failed);
      setOutcome(found);
      setRecomputed(true);
      setSort([]);
      setFilter("");
      setDrawn(ROWS_PER_PAGE);
      // The reader asked to see this one, whatever its shape.
      setKind(showsResult({ ok: true, result: found.result, exported: false, display: "result" }));
    } catch (error) {
      setFailure(error instanceof Error ? error.message : text.failed);
    } finally {
      setBusy(false);
    }
  };
  const reset = () => {
    if (!original) return;
    setDraft(editableInput(args.input));
    setOutcome(original);
    setRecomputed(false);
    setFailure(undefined);
    setKind(
      showsResult({
        ok: original.ok,
        result: original.result,
        exported: original.export !== undefined,
        display: args.display ?? "auto",
      }),
    );
  };

  const fullscreen = host.context.displayMode === "fullscreen";
  const logs =
    outcome?.logs && outcome.logs.length > 0
      ? outcome.logs.join("\n") +
        (outcome.dropped_log_lines ? `\n… ${text.dropped(outcome.dropped_log_lines)}` : "")
      : undefined;

  const title =
    typeof args.title === "string" && args.title.trim()
      ? args.title.trim()
      : table
        ? filter.trim()
          ? text.matching(matching.length, table.rows.length)
          : text.rows(table.rows.length)
        : text.result;

  return (
    <ViewFrame
      host={host}
      name="compute-result"
      shown={shown}
      label={text.label}
      title={title}
      controls={
        <>
          {table && (
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
          )}
          <Button
            variant="ghost"
            label={copied ? text.copied : text.copy}
            icon={<Icon icon={copied ? "check" : "copy"} />}
            onClick={copy}
          />
        </>
      }
      notices={
        failure && <Banner status="error" container="section" title={text.failed} description={failure} />
      }
      footer={
        <>
          <Toolbar
            label={text.detailsLabel}
            dividers={["top"]}
            startContent={
              recomputed ? (
                <>
                  <Badge label={text.recomputed} />
                  <Button variant="ghost" size="sm" label={text.reset} icon={undoIcon} onClick={reset} />
                </>
              ) : (
                <Text type="supporting" color="secondary">
                  {[
                    outcome?.export && typeof outcome.export.rows === "number"
                      ? text.preview(
                          typeof outcome.export.preview_rows === "number"
                            ? outcome.export.preview_rows
                            : (table?.rows.length ?? 0),
                          outcome.export.rows,
                        )
                      : undefined,
                    typeof outcome?.duration_ms === "number"
                      ? text.duration(outcome.duration_ms)
                      : undefined,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </Text>
              )
            }
            endContent={
              <Button
                variant="ghost"
                label={open ? text.hideDetails : text.details}
                icon={codeIcon}
                endContent={open ? chevronUpIcon : chevronDownIcon}
                aria-expanded={open}
                onClick={() => setOpen((value) => !value)}
              />
            }
          />
          {open && (
            <div className="eneo-details">
              <TabList value={tab} onChange={setTab} size="sm" hasDivider aria-label={text.detailsLabel}>
                <Tab value="code" label={text.code} />
                <Tab value="input" label={text.input} />
                {logs && <Tab value="logs" label={text.logs} />}
              </TabList>
              <div className="eneo-panel" role="tabpanel">
                {tab === "code" && (
                  <CodeBlock
                    code={typeof args.code === "string" ? args.code : ""}
                    language="javascript"
                    title={text.language}
                    hasLanguageLabel={false}
                    hasLineNumbers
                    size="sm"
                    width="100%"
                    maxHeight={fullscreen ? undefined : 288}
                  />
                )}
                {tab === "input" &&
                  (draft ? (
                    <>
                      <div className="eneo-fields">
                        {Object.entries(draft).map(([key, field]) =>
                          typeof field === "number" ? (
                            <NumberInput
                              key={key}
                              label={labelOf(key)}
                              value={field}
                              onChange={(next: number | null) =>
                                setDraft({ ...draft, [key]: next ?? 0 })
                              }
                            />
                          ) : typeof field === "boolean" ? (
                            <Switch
                              key={key}
                              label={labelOf(key)}
                              value={field}
                              onChange={(next) => setDraft({ ...draft, [key]: next })}
                            />
                          ) : (
                            <TextInput
                              key={key}
                              label={labelOf(key)}
                              value={field}
                              onChange={(next: string) => setDraft({ ...draft, [key]: next })}
                            />
                          ),
                        )}
                      </div>
                      <div className="eneo-actions">
                        <Button
                          variant="secondary"
                          label={busy ? text.running : text.rerun}
                          icon={playIcon}
                          isLoading={busy}
                          onClick={() => void rerun()}
                        />
                        <Text type="supporting" color="secondary">
                          {text.rerunNote}
                        </Text>
                      </div>
                    </>
                  ) : args.input === undefined || args.input === null ? (
                    <EmptyState isCompact title={text.noInputTitle} description={text.noInput} />
                  ) : (
                    <CodeBlock
                      code={JSON.stringify(args.input, null, 2)}
                      language="json"
                      hasLanguageLabel={false}
                      size="sm"
                      width="100%"
                      maxHeight={fullscreen ? undefined : 288}
                    />
                  ))}
                {tab === "logs" && logs && (
                  <CodeBlock
                    code={logs}
                    hasLanguageLabel={false}
                    size="sm"
                    width="100%"
                    maxHeight={fullscreen ? undefined : 288}
                  />
                )}
              </div>
            </div>
          )}
        </>
      }
    >
      {table ? (
        <>
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
                actions={<Button variant="secondary" label={text.clear} onClick={() => setFilter("")} />}
              />
            }
          />
          {matching.length > drawn && (
            <div className="eneo-actions">
              <Button
                variant="secondary"
                label={text.more}
                onClick={() => setDrawn((count) => count + ROWS_PER_PAGE)}
              />
            </div>
          )}
        </>
      ) : isFlatObject(value) ? (
        <Table<Row>
          data={Object.entries(value).map(([key, cell]) => ({ id: key, key, cell }))}
          columns={[
            { key: "key", header: text.key, renderCell: (item: Row) => labelOf(String(item.key)) },
            {
              key: "cell",
              header: text.value,
              align: "end" as const,
              renderCell: (item: Row) =>
                item.cell === null || item.cell === undefined ? (
                  <Text color="disabled">–</Text>
                ) : (
                  shownCell(item.cell)
                ),
            },
          ]}
          idKey="id"
          density="compact"
          dividers="rows"
          scrollWrapper={TableRows}
        />
      ) : typeof value === "object" && value !== null ? (
        <CodeBlock
          code={JSON.stringify(value, null, 2)}
          language="json"
          hasLanguageLabel={false}
          hasCopyButton={false}
          container="section"
          size="sm"
          width="100%"
        />
      ) : (
        <div className="eneo-value">{value === null || value === undefined ? "null" : shownCell(value)}</div>
      )}
    </ViewFrame>
  );
}

createRoot(document.getElementById("app")!).render(<ResultView />);
