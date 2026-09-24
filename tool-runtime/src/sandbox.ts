import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ToolError } from "./errors";
import type { SandboxJob } from "./child";

const ROOT = join(tmpdir(), "eneo-tool-runtime-jobs");
const MAX_STDOUT_BYTES = 600 * 1024;
const WATCHDOG = "/usr/bin/timeout";
const CHILD_PATH = new URL("./child.ts", import.meta.url).pathname;

/**
 * Runs one job in a fresh child process. The child inherits nothing from this process except
 * PATH: no bearer token, no service credentials, no other job's data. It gets a private
 * temporary directory that is removed afterwards, a bounded stdout and a hard deadline enforced
 * both here and by an external watchdog that survives an abrupt parent exit.
 */
export async function runIsolated(
  job: SandboxJob,
  timeoutMs: number,
): Promise<Record<string, unknown>> {
  await mkdir(ROOT, { recursive: true, mode: 0o700 });
  const directory = await mkdtemp(join(ROOT, `${process.pid}-`));
  const env: Record<string, string> = { TMPDIR: directory };
  if (process.env.PATH) env.PATH = process.env.PATH;
  const seconds = Math.ceil(timeoutMs / 1000);
  const [command, args] = existsSync(WATCHDOG)
    ? [WATCHDOG, ["--signal=KILL", `${seconds}s`, process.execPath, CHILD_PATH]]
    : [process.execPath, [CHILD_PATH]];
  try {
    return await new Promise((resolve, reject) => {
      const child = spawn(command, args, {
        detached: true,
        cwd: directory,
        stdio: ["pipe", "pipe", "ignore"],
        env,
      });
      const chunks: Buffer[] = [];
      let size = 0;
      let failure: Error | undefined;
      const kill = () => {
        try {
          if (child.pid) process.kill(-child.pid, "SIGKILL");
        } catch {
          child.kill("SIGKILL");
        }
      };
      const timer = setTimeout(() => {
        failure = new ToolError("TIMEOUT", "Operation exceeded its whole-job deadline.");
        kill();
      }, timeoutMs);
      child.stdout.on("data", (chunk: Buffer) => {
        size += chunk.length;
        if (size > MAX_STDOUT_BYTES) {
          failure = new ToolError("RESULT_TOO_LARGE", "Result exceeded the byte limit.");
          kill();
        } else chunks.push(chunk);
      });
      child.on("error", (error) => {
        failure = error;
      });
      child.stdin.on("error", () => {});
      child.on("close", (code) => {
        clearTimeout(timer);
        if (failure || code !== 0) {
          reject(failure ?? new ToolError("SANDBOX_CRASH", "Execution process failed."));
          return;
        }
        try {
          const message = JSON.parse(Buffer.concat(chunks).toString());
          if (!message.ok) reject(new ToolError(message.error.code, message.error.message));
          else resolve(message.result);
        } catch {
          reject(new ToolError("SANDBOX_CRASH", "Execution process returned an invalid result."));
        }
      });
      child.stdin.end(JSON.stringify(job));
    });
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

/** Allows at most `slots` concurrent calls; the rest wait in arrival order. */
export function concurrencyLimit(slots: number) {
  let active = 0;
  const waiting: Array<() => void> = [];
  return async function run<T>(task: () => Promise<T>): Promise<T> {
    // A released slot passes straight to the next waiter, so a newcomer cannot take it between
    // the release and the hand-over.
    if (active >= slots) await new Promise<void>((resolve) => waiting.push(resolve));
    else active++;
    try {
      return await task();
    } finally {
      const next = waiting.shift();
      if (next) next();
      else active--;
    }
  };
}
