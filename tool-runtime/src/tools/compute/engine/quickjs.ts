// Script execution runs in sandbox children only. QuickJS is a separate JavaScript engine
// compiled to WebAssembly: the script sees nothing of the host (no fetch, fs, process, timers,
// modules) except the console object and the input value installed here, and every run gets a
// fresh runtime with its own memory and time limits. The tool entrypoint (tool.ts) never
// imports this file.
import {
  newQuickJSWASMModuleFromVariant,
  shouldInterruptAfterDeadline,
  type QuickJSContext,
  type QuickJSHandle,
  type QuickJSWASMModule,
} from "quickjs-emscripten-core";
import variant from "@jitl/quickjs-ng-wasmfile-release-sync";
import { writeFile } from "node:fs/promises";
import { toCsv } from "../../files/csv";
import { MAX_LOG_LINE_CHARS, PREVIEW_ROWS, type ComputeConfig } from "../config";
import type { ComputeExport, ComputeJob, ComputeOutcome, ScriptErrorCode } from "../ports";
import { asTabular, describeShape, previewRows } from "../shape";
import { loadPrelude } from "./prelude";

const STACK_BYTES = 512 * 1024;
const FILENAME = "script.js";
const CONSOLE_METHODS = ["log", "info", "warn", "error", "debug"] as const;
let engine: Promise<QuickJSWASMModule> | undefined;
function loadEngine() {
  engine ??= newQuickJSWASMModuleFromVariant(variant);
  return engine;
}
type Failure = NonNullable<ComputeOutcome["error"]>;
// The script is wrapped in one async function, so its first line is line 2 of the eval unit.
function scriptLine(stack: unknown): number | undefined {
  if (typeof stack !== "string") return undefined;
  const match = new RegExp(`${FILENAME}:(\\d+)`).exec(stack);
  if (!match) return undefined;
  const line = Number(match[1]) - 1;
  return line >= 1 ? line : undefined;
}
function describeError(vm: QuickJSContext, handle: QuickJSHandle, syntax = false): Failure {
  const dumped: unknown = vm.dump(handle);
  const record =
    typeof dumped === "object" && dumped !== null ? (dumped as Record<string, unknown>) : {};
  const name = typeof record.name === "string" ? record.name : "Error";
  const message =
    typeof record.message === "string"
      ? record.message
      : typeof dumped === "string"
        ? dumped
        : String(dumped ?? "Unknown error");
  const truncated =
    message.length > MAX_LOG_LINE_CHARS ? `${message.slice(0, MAX_LOG_LINE_CHARS)}…` : message;
  let code: ScriptErrorCode = syntax || name === "SyntaxError" ? "SYNTAX_ERROR" : "RUNTIME_ERROR";
  if (name === "InternalError" && /interrupted/.test(message)) code = "TIMEOUT";
  else if (name === "InternalError" && /out of memory/.test(message)) code = "OUT_OF_MEMORY";
  else if (name === "RangeError" && /stack overflow/i.test(message)) code = "RUNTIME_ERROR";
  const line = scriptLine(record.stack);
  return {
    code,
    name,
    message:
      code === "TIMEOUT"
        ? "The script exceeded its time limit."
        : code === "OUT_OF_MEMORY"
          ? "The script exceeded its memory limit."
          : truncated,
    ...(line !== undefined ? { line } : {}),
  };
}
function formatLogValue(vm: QuickJSContext, handle: QuickJSHandle): string {
  const type = vm.typeof(handle);
  if (type === "string") return vm.getString(handle);
  if (type === "undefined") return "undefined";
  if (type === "function") return "[function]";
  try {
    const value: unknown = vm.dump(handle);
    if (value === undefined) return "undefined";
    return typeof value === "string" ? value : (JSON.stringify(value) ?? String(value));
  } catch {
    return "[unserialisable]";
  }
}
function installConsole(
  vm: QuickJSContext,
  logs: string[],
  maxLines: number,
  dropped: { count: number },
) {
  const console = vm.newObject();
  for (const method of CONSOLE_METHODS) {
    const fn = vm.newFunction(method, (...args) => {
      const line = args.map((arg) => formatLogValue(vm, arg)).join(" ");
      if (logs.length >= maxLines) {
        dropped.count++;
        return;
      }
      logs.push(line.length > MAX_LOG_LINE_CHARS ? `${line.slice(0, MAX_LOG_LINE_CHARS)}…` : line);
    });
    vm.setProp(console, method, fn);
    fn.dispose();
  }
  vm.setProp(vm.global, "console", console);
  console.dispose();
}
function installInput(vm: QuickJSContext, input: unknown) {
  const json = vm.newString(JSON.stringify(input ?? null));
  vm.setProp(vm.global, "__input", json);
  json.dispose();
  const parsed = vm.evalCode(
    "globalThis.input = JSON.parse(globalThis.__input); delete globalThis.__input; undefined",
    "input.js",
  );
  if (parsed.error) parsed.error.dispose();
  else parsed.value.dispose();
}
function serialize(
  vm: QuickJSContext,
  handle: QuickJSHandle,
  maxBytes: number,
  exporting: boolean,
): { result: unknown } | { error: Failure } {
  if (vm.typeof(handle) === "undefined") return { result: null };
  const stringify = vm.evalCode("(value) => JSON.stringify(value)", "serialize.js");
  const fn = vm.unwrapResult(stringify);
  try {
    const called = vm.callFunction(fn, vm.undefined, handle);
    if (called.error) {
      const failure = describeError(vm, called.error);
      called.error.dispose();
      return {
        error: {
          code: "RESULT_NOT_SERIALIZABLE",
          name: failure.name,
          message: `The returned value cannot be converted to JSON: ${failure.message}`,
        },
      };
    }
    const text = vm.typeof(called.value) === "string" ? vm.getString(called.value) : undefined;
    called.value.dispose();
    if (text === undefined) return { result: null };
    if (Buffer.byteLength(text) > maxBytes)
      return {
        error: {
          code: "RESULT_TOO_LARGE",
          name: "RangeError",
          message: exporting
            ? `The returned value exceeds ${maxBytes} bytes as JSON. Return fewer rows or columns.`
            : `The returned value exceeds ${maxBytes} bytes as JSON. Return a summary or a smaller slice, or set export=true to deliver a tabular value as a CSV file.`,
        },
      };
    return { result: JSON.parse(text) };
  } finally {
    fn.dispose();
  }
}
/**
 * Writes the returned table to the job's export file and keeps a preview of it, in the shape
 * the script returned, that fits the inline result limit. A value that is not a table is a
 * script-level failure the model can fix by reshaping it or dropping export.
 */
async function exportResult(
  value: unknown,
  target: ComputeExport,
  config: ComputeConfig,
): Promise<Pick<ComputeOutcome, "result" | "export"> | { error: Failure }> {
  const table = asTabular(value);
  if (!table)
    return {
      error: {
        code: "RESULT_NOT_TABULAR",
        name: "TypeError",
        message: `export=true needs a tabular value: an array of objects with the same keys, or an array of arrays whose first row holds the column names. The script returned ${describeShape(value)}. Reshape it (for example rows.map((v) => ({ value: v }))) or call again with export=false.`,
      },
    };
  const rows = table.rows.slice(0, target.rowLimit);
  await writeFile(target.outputPath, toCsv(table.columns, rows), { mode: 0o600 });
  let count = Math.min(PREVIEW_ROWS, rows.length);
  let preview = previewRows(value as unknown[], table.form, count);
  while (count > 0 && Buffer.byteLength(JSON.stringify(preview)) > config.max_result_bytes) {
    count = Math.floor(count / 2);
    preview = previewRows(value as unknown[], table.form, count);
  }
  return {
    result: preview,
    export: {
      columns: table.columns,
      rows: rows.length,
      truncated: table.rows.length > rows.length,
      preview_rows: count,
    },
  };
}
export async function runJavaScript(
  job: ComputeJob,
  config: ComputeConfig,
): Promise<ComputeOutcome> {
  const [QuickJS, prelude] = await Promise.all([loadEngine(), loadPrelude()]);
  const runtime = QuickJS.newRuntime();
  const vm = runtime.newContext();
  const logs: string[] = [];
  const dropped = { count: 0 };
  const started = performance.now();
  const finish = (
    partial: Pick<ComputeOutcome, "result" | "export"> | { error: Failure },
  ): ComputeOutcome => ({
    ok: !("error" in partial),
    ...partial,
    logs,
    dropped_log_lines: dropped.count,
    duration_ms: Math.round(performance.now() - started),
  });
  try {
    runtime.setMemoryLimit(config.memory_mb * 1024 * 1024);
    runtime.setMaxStackSize(STACK_BYTES);
    // The prelude (Decimal, fmt) is trusted code evaluated inside the memory limit but before
    // the script's deadline starts, so the script keeps its whole time budget.
    const installed = vm.evalCode(prelude, "prelude.js", { type: "global", strict: true });
    if (installed.error) {
      const failure = describeError(vm, installed.error);
      installed.error.dispose();
      throw new Error(`The compute prelude failed to install: ${failure.message}`);
    }
    installed.value.dispose();
    runtime.setInterruptHandler(shouldInterruptAfterDeadline(Date.now() + config.timeout_ms));
    installConsole(vm, logs, config.max_log_lines, dropped);
    installInput(vm, job.input);
    const evaluated = vm.evalCode(`(async () => {\n${job.code}\n})()`, FILENAME);
    if (evaluated.error) {
      const failure = describeError(vm, evaluated.error, true);
      evaluated.error.dispose();
      return finish({ error: failure });
    }
    const promise = evaluated.value;
    try {
      // Microtasks and awaited continuations run here; nothing else can schedule work later.
      const jobs = runtime.executePendingJobs();
      if (jobs.error) {
        const failure = describeError(vm, jobs.error);
        jobs.error.dispose();
        return finish({ error: failure });
      }
      const state = vm.getPromiseState(promise);
      if (state.type === "pending")
        return finish({
          error: {
            code: "UNSETTLED_PROMISE",
            name: "Error",
            message:
              "The script awaited a promise that never settles. The sandbox has no timers or I/O; remove the await or resolve the promise synchronously.",
          },
        });
      if (state.type === "rejected") {
        const failure = describeError(vm, state.error);
        state.error.dispose();
        return finish({ error: failure });
      }
      const serialized = (() => {
        try {
          return serialize(
            vm,
            state.value,
            job.export ? job.export.maxBytes : config.max_result_bytes,
            job.export !== undefined,
          );
        } finally {
          state.value.dispose();
        }
      })();
      if ("error" in serialized || !job.export) return finish(serialized);
      return finish(await exportResult(serialized.result, job.export, config));
    } finally {
      promise.dispose();
    }
  } finally {
    vm.dispose();
    runtime.dispose();
  }
}
