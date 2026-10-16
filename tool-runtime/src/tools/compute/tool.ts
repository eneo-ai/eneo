import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { z } from "zod";
import { ToolError } from "../../errors";
import { exportFilename, MAX_EXPORT_BYTES } from "../files/csv";
import { RichResult, type ToolDefinition, type ToolView } from "../types";
import type { ComputeConfig } from "./config";
import type { ComputeJob, ComputeOutcome } from "./ports";
import { showsResult } from "./shape";

export type ComputeExecutor = (job: ComputeJob) => Promise<ComputeOutcome>;

export const TABLE_SHOWN =
  "The user sees these rows as a table directly under your answer, which they can sort, filter, copy and expand; the code, input and logs sit behind a disclosure there, and they can run the same code again over edited input. Do not write the rows out again or list the columns; introduce the table briefly and explain the relevant findings.";
export const EXPORT_SHOWN =
  "The user sees the first rows of the exported table directly under your answer as a preview, with the code behind a disclosure, and gets the whole result as the attached file. Do not write the rows out again; say what the file holds and explain the relevant findings.";
export const VALUE_SHOWN =
  "The user sees the returned value directly under your answer, with the code, input and logs behind a disclosure, and can run the same code again over edited input. Do not repeat the value verbatim or paste the code; say what it means.";

/**
 * @param view The result view shown with a run, in hosts that show tool views.
 */
export function computeTools(
  config: ComputeConfig,
  run: ComputeExecutor,
  view?: ToolView,
): ToolDefinition[] {
  const input = z.object({
    code: z
      .string()
      .min(1)
      .max(config.max_code_chars)
      .describe(
        `JavaScript (ES2023) source, at most ${config.max_code_chars} characters. It runs as the body of an async function: use return to produce the result and await where needed. The global input holds the input argument; console.log output is returned as logs.`,
      ),
    input: z
      .json()
      .optional()
      .describe(
        "JSON value (object, array, string, number) made available to the code as the global input. Always pass the values the user gave or might want to change (amounts, rates, years, names) here as a flat object, e.g. { amount: 1234.5, rate: 0.12 }, and read them from input in the code instead of writing them as literals: the user then gets fields to edit them and a button to run the code again. Put larger data here too rather than inlining it in the code.",
      ),
    export: z
      .boolean()
      .default(false)
      .describe(
        "Leave false unless the user asks for a downloadable file, create_spreadsheet needs the rows as a file, or a chart needs more than about 50 rows; a smaller table goes to create_chart as labels and series, since an export is shown to the user as a downloadable file. Then return a tabular value: an array of objects with the same keys, or an array of arrays whose first row holds the column names. The whole table is attached as a CSV file and result keeps only the first rows as a preview.",
      ),
    export_filename: z
      .string()
      .max(100)
      .optional()
      .describe("File name for the exported CSV, without extension."),
    display: z
      .enum(["auto", "result", "none"])
      .default("auto")
      .describe(
        "auto shows the value as an interactive table under your answer only when it is a table with several rows. result shows the value whatever its shape (a number, a key/value list or JSON) when the user asked to see the result or the calculation. none hides the view for intermediate calculations. Every mode returns the same data to you.",
      ),
    title: z
      .string()
      .max(120)
      .optional()
      .describe(
        "Short caption in the user's language for a shown result, such as 'Ränta per år'. Give one when display is result or the value is a table; the host lists the conversation's views by it.",
      ),
  });
  return [
    {
      name: "run_javascript",
      title: "Run JavaScript",
      ...(view ? { view } : {}),
      description:
        "Run JavaScript in an isolated sandbox and get the returned value back. Use it for arithmetic and statistics that must be exact, unit and currency conversion, date arithmetic, sorting, grouping, deduplication, parsing or reshaping data you already have, regular expressions and string formatting. Write the code as the body of an async function and return a JSON-serialisable value; pass the user's values in the input argument and read them from the global input rather than writing them into the code; console.log lines come back as logs. For a table, return the array of row objects itself as the result, not wrapped in an object with other keys (say such things in your answer instead), and name columns, the keys of a returned object and the keys of input readably in the user's language (e.g. 'Ränta (kr)', 'belopp'): they are shown to the user as labels. The sandbox has the standard ECMAScript library plus two preinstalled globals: Decimal (decimal.js, exact decimal arithmetic, e.g. new Decimal('0.1').plus('0.2'); return a Decimal result as a number with toNumber(), exact up to 15 significant digits, so the reader sees it formatted; a returned Decimal or a toFixed string arrives as text) and fmt for Swedish formatting (fmt.number(1234.5, { decimals: 2 }) is '1 234,50', fmt.percent(0.256) is '25,6 %', fmt.date(d) is 'YYYY-MM-DD', fmt.datetime(d) adds HH:mm; dates are UTC). There is no Intl, network, file system, timers, imports, require or Node and Bun APIs, and no state between calls, so pass in everything the code needs. Errors thrown by the code, time and memory limits and oversized results are reported in the result with ok=false so you can fix the code and retry. With export=true a tabular value is attached as a CSV file for the user and as a source for create_chart and create_spreadsheet; result then holds only a preview and export.rows says how many rows the file has. When the result includes shown, follow it and do not repeat what the user already sees; otherwise report the returned value yourself. Not for data that sits in an attached file: the file tools (inspect_table, query_table) read the file itself and are exact, so use them for its totals, groupings and comparisons; use this tool for values in the conversation or results you already computed. Do not use it to fetch data; report the returned value, not the code, unless the user asked to see it.",
      inputSchema: input.shape,
      readOnly: true,
      async execute(raw, ctx) {
        const args = input.parse(raw);
        const payload = args.input === undefined ? null : args.input;
        if (Buffer.byteLength(JSON.stringify(payload)) > config.max_input_bytes)
          throw new ToolError(
            "INPUT_TOO_LARGE",
            `The input exceeds ${config.max_input_bytes} bytes. Pass a smaller value or aggregate it first.`,
          );
        // The child writes the export into a directory this process owns.
        const directory = args.export
          ? await mkdtemp(join(tmpdir(), "eneo-tool-runtime-export-"))
          : undefined;
        try {
          const outputPath = directory ? join(directory, "result.csv") : undefined;
          const outcome = await run({
            kind: "compute",
            code: args.code,
            input: payload,
            ...(outputPath
              ? {
                  export: {
                    outputPath,
                    rowLimit: config.export_row_limit,
                    maxBytes: config.max_export_bytes,
                  },
                }
              : {}),
          });
          // Where Eneo shows the value, the model is told, so it is not written out again.
          const kind =
            view !== undefined && ctx.showsViews === true
              ? showsResult({
                  ok: outcome.ok,
                  result: outcome.result,
                  exported: args.export,
                  display: args.display,
                })
              : false;
          const structured = {
            ok: outcome.ok,
            ...(outcome.ok ? { result: outcome.result ?? null } : { error: outcome.error }),
            logs: outcome.logs,
            ...(outcome.dropped_log_lines ? { dropped_log_lines: outcome.dropped_log_lines } : {}),
            duration_ms: outcome.duration_ms,
            display: args.display,
            ...(kind === "table" ? { shown: args.export ? EXPORT_SHOWN : TABLE_SHOWN } : {}),
            ...(kind === "value" ? { shown: VALUE_SHOWN } : {}),
          };
          if (!outputPath || !outcome.ok || !outcome.export) return structured;
          const csv = await readFile(outputPath);
          if (csv.length > MAX_EXPORT_BYTES)
            throw new ToolError(
              "EXPORT_TOO_LARGE",
              "The exported result exceeds the file size limit. Return fewer rows or columns.",
            );
          const filename = exportFilename(args.export_filename);
          return new RichResult(
            {
              ...structured,
              export: {
                filename,
                columns: outcome.export.columns,
                rows: outcome.export.rows,
                preview_rows: outcome.export.preview_rows,
                truncated: outcome.export.truncated,
                delivered:
                  "The full result is attached as a CSV file for the user. Use its reference url for further tools; result holds only the first rows as a preview.",
              },
            },
            [
              {
                uri: `eneo-tool-runtime://compute/${crypto.randomUUID()}/${encodeURIComponent(filename)}`,
                mimeType: "text/csv",
                blob: csv.toString("base64"),
              },
            ],
          );
        } finally {
          if (directory) await rm(directory, { recursive: true, force: true });
        }
      },
    },
  ];
}
