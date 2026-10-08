import { checkCancellation, work } from "./work";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { ToolError } from "./errors";
import { REQUIRE_CONFINEMENT, type SandboxJob } from "./child";

const ROOT = join(tmpdir(), "eneo-tool-runtime-jobs");
const MAX_STDOUT_BYTES = 600 * 1024;
const WATCHDOG = "/usr/bin/timeout";
const RUNTIME_ROOT = new URL("..", import.meta.url).pathname;
const CHILD_PATH = join(RUNTIME_ROOT, "src", "child.ts");
// landrun (github.com/zouuup/landrun) applies Landlock to a command before it starts. The
// image installs it; elsewhere `bun run build:landrun` puts it in bin/.
const LANDRUN = [join(RUNTIME_ROOT, "bin", "landrun"), "/usr/local/bin/landrun"];

// What a Bun child needs whatever its job: its own binary and the dynamic loader, shared
// libraries, this runtime's code, fonts, time zones, the container's memory and CPU limits,
// random numbers and its own /proc entries. None of it is another job's data.
const BASE_RULES = [
  ["--rox", process.execPath],
  ["--rox", "/usr/lib"],
  ["--rox", "/lib"],
  ["--rox", "/lib64"],
  ["--ro", "/etc/ld.so.cache"],
  // Bun walks up from its working directory at start-up and must be able to read every
  // directory it passes, so the child runs in the runtime's own directory and may read from
  // the top of that tree: /app in the image, where it holds nothing but this code.
  ["--ro", `/${RUNTIME_ROOT.split("/")[1]}`],
  ["--ro", "/usr/share/fonts"],
  ["--ro", "/usr/local/share/fonts"],
  ["--ro", "/usr/share/zoneinfo"],
  ["--ro", "/etc/localtime"],
  ["--ro", "/sys/fs/cgroup"],
  ["--ro", "/sys/devices/system/cpu"],
  ["--ro", "/proc/self"],
  ["--ro", "/dev/urandom"],
  ["--rw", "/dev/null"],
].flat();

/** The files one job may touch beyond its private directory. */
export type JobPaths = { read?: string[]; write?: string[] };

/**
 * The files each kind of job needs. A compromised child can open these and nothing else of
 * another job's, so every path here is one the parent chose for this job alone. A new job
 * kind does not compile until it has an entry.
 */
export function jobPaths(job: SandboxJob["job"]): JobPaths {
  switch (job.kind) {
    case "compute":
    case "env":
    case "confinement":
      return {};
    case "tabular_ingest":
      return { read: [job.inputPath], write: [job.outputDir] };
    case "tabular_query":
      return {
        read: [job.csvPath, ...job.tables.map((table) => table.csvPath)],
        write: job.export ? [dirname(job.export.outputPath)] : [],
      };
    case "render_document":
      // Sources and the template sit next to the output, in a directory made for this job.
      return { write: [dirname(job.outputPath)] };
    case "render_chart":
      // An XLSX source is converted to CSV next to itself.
      return { write: job.source?.path ? [dirname(job.source.path)] : [] };
  }
}

export type SandboxOptions = {
  /** Refuse to run a job that is not confined (TOOL_RUNTIME_REQUIRE_CONFINEMENT). */
  requireConfinement?: boolean;
  signal?: AbortSignal;
};

/**
 * The launcher prefix that confines a child to `directory` and its job's declared files.
 * Empty when landrun is not installed, which leaves the child as unconfined as it is on a
 * kernel without Landlock; a child that must be confined checks that for itself.
 */
export function confinement(job: SandboxJob, directory: string): string[] {
  const landrun = LANDRUN.find((path) => existsSync(path));
  if (!landrun) return [];
  const paths = jobPaths(job.job);
  return [
    landrun,
    // Use what this kernel offers: files since 5.13, TCP since 6.7. Paths that a slimmer
    // image lacks (a font directory, /lib64) are skipped.
    "--best-effort",
    "--ignore-missing",
    ...["--env", "PATH", "--env", "TMPDIR"],
    ...BASE_RULES,
    ...["--rw", directory],
    ...(paths.read ?? []).flatMap((path) => ["--ro", path]),
    ...(paths.write ?? []).flatMap((path) => ["--rw", path]),
    "--",
  ];
}

/**
 * Runs one job in a fresh child process. The child inherits nothing from this process except
 * PATH: no bearer token, no service credentials, no other job's data. It gets a private
 * temporary directory that is removed afterwards, a bounded stdout and a hard deadline enforced
 * both here and by an external watchdog that survives an abrupt parent exit. Where the kernel
 * has Landlock and landrun is installed, the child is confined before it starts: it can open
 * only its own directory and the files its job declares, and has no TCP, so even a compromised
 * engine cannot read another job's files, the parsed-sheet cache or this process's environment.
 */
export async function runIsolated(
  job: SandboxJob,
  timeoutMs: number,
  options: SandboxOptions = {},
): Promise<Record<string, unknown>> {
  const signal = options.signal ?? work.getStore()?.signal;
  checkCancellation(signal);
  await mkdir(ROOT, { recursive: true, mode: 0o700 });
  const directory = await mkdtemp(join(ROOT, `${process.pid}-`));
  const env: Record<string, string> = { TMPDIR: directory };
  if (process.env.PATH) env.PATH = process.env.PATH;
  const seconds = Math.ceil(timeoutMs / 1000);
  try {
    const launcher = confinement(job, directory);
    const target = [
      ...launcher,
      process.execPath,
      CHILD_PATH,
      ...(options.requireConfinement ? [REQUIRE_CONFINEMENT] : []),
    ];
    const [command, ...args] = existsSync(WATCHDOG)
      ? [WATCHDOG, "--signal=KILL", `${seconds}s`, ...target]
      : target;
    return await new Promise((resolve, reject) => {
      const child = spawn(command!, args, {
        detached: true,
        // A confined child cannot write here, so nothing it does may depend on the working
        // directory: scratch files go to TMPDIR, its private directory.
        cwd: launcher.length ? RUNTIME_ROOT : directory,
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
      const abort = () => {
        failure =
          signal?.reason instanceof ToolError
            ? signal.reason
            : new ToolError("CANCELLED", "The operation was cancelled.");
        kill();
      };
      signal?.addEventListener("abort", abort, { once: true });
      if (signal?.aborted) abort();
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
        signal?.removeEventListener("abort", abort);
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
