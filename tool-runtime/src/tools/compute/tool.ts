import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { z } from "zod";
import { ToolError } from "../../errors";
import { exportFilename, MAX_EXPORT_BYTES } from "../files/csv";
import { RichResult, type ToolDefinition } from "../types";
import type { ComputeConfig } from "./config";
import type { ComputeJob, ComputeOutcome } from "./ports";

export type ComputeExecutor = (job: ComputeJob) => Promise<ComputeOutcome>;

export function computeTools(config: ComputeConfig, run: ComputeExecutor): ToolDefinition[] {
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
        "Optional JSON value (object, array, string, number) made available to the code as the global input. Put data here rather than inlining large literals in the code.",
      ),
    export: z
      .boolean()
      .default(false)
      .describe(
        "Leave false unless the user asks for a downloadable file or the rows are needed as a source file by create_spreadsheet or create_chart. Then return a tabular value: an array of objects with the same keys, or an array of arrays whose first row holds the column names. The whole table is attached as a CSV file and result keeps only the first rows as a preview.",
      ),
    export_filename: z
      .string()
      .max(100)
      .optional()
      .describe("File name for the exported CSV, without extension."),
  });
  return [
    {
      name: "run_javascript",
      title: "Run JavaScript",
      description:
        "Run JavaScript in an isolated sandbox and get the returned value back. Use it for arithmetic and statistics that must be exact, unit and currency conversion, date arithmetic, sorting, grouping, deduplication, parsing or reshaping data you already have, regular expressions and string formatting. Write the code as the body of an async function and return a JSON-serialisable value; read the optional argument from the global input; console.log lines come back as logs. The sandbox has the standard ECMAScript library only: no network, file system, timers, imports, require or Node and Bun APIs, and no state between calls, so pass in everything the code needs. Errors thrown by the code, time and memory limits and oversized results are reported in the result with ok=false so you can fix the code and retry. With export=true a tabular value is attached as a CSV file for the user and as a source for create_chart and create_spreadsheet; result then holds only a preview and export.rows says how many rows the file has. Do not use it to fetch data; report the returned value, not the code, unless the user asked to see it.",
      inputSchema: input.shape,
      readOnly: true,
      async execute(raw) {
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
          const structured = {
            ok: outcome.ok,
            ...(outcome.ok ? { result: outcome.result ?? null } : { error: outcome.error }),
            logs: outcome.logs,
            ...(outcome.dropped_log_lines ? { dropped_log_lines: outcome.dropped_log_lines } : {}),
            duration_ms: outcome.duration_ms,
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
