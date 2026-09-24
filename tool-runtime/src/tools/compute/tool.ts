import { z } from "zod";
import { ToolError } from "../../errors";
import type { ComputeConfig } from "./config";
import type { ComputeJob, ComputeOutcome } from "./ports";

export type ComputeExecutor = (job: ComputeJob) => Promise<ComputeOutcome>;

export type ToolDefinition = {
  name: string;
  title: string;
  description: string;
  inputSchema: z.ZodRawShape;
  readOnly: boolean;
  execute(raw: unknown): Promise<Record<string, unknown>>;
};

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
  });
  return [
    {
      name: "run_javascript",
      title: "Run JavaScript",
      description:
        "Run JavaScript in an isolated sandbox and get the returned value back. Use it for arithmetic and statistics that must be exact, unit and currency conversion, date arithmetic, sorting, grouping, deduplication, parsing or reshaping data you already have, regular expressions and string formatting. Write the code as the body of an async function and return a JSON-serialisable value; read the optional argument from the global input; console.log lines come back as logs. The sandbox has the standard ECMAScript library only: no network, file system, timers, imports, require or Node and Bun APIs, and no state between calls, so pass in everything the code needs. Errors thrown by the code, time and memory limits and oversized results are reported in the result with ok=false so you can fix the code and retry. Do not use it to fetch data; report the returned value, not the code, unless the user asked to see it.",
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
        const outcome = await run({ kind: "compute", code: args.code, input: payload });
        return {
          ok: outcome.ok,
          ...(outcome.ok ? { result: outcome.result ?? null } : { error: outcome.error }),
          logs: outcome.logs,
          ...(outcome.dropped_log_lines ? { dropped_log_lines: outcome.dropped_log_lines } : {}),
          duration_ms: outcome.duration_ms,
        };
      },
    },
  ];
}
