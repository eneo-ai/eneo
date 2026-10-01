import { describe, expect, test } from "bun:test";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { REQUIRE_CONFINEMENT } from "../src/child";
import { computeConfigSchema } from "../src/tools/compute/config";
import { tabularConfigSchema } from "../src/tools/tabular/config";
import { concurrencyLimit, confinement, runIsolated } from "../src/sandbox";

const config = computeConfigSchema.parse({});

describe("sandbox child", () => {
  test("inherits no environment beyond PATH and its private TMPDIR", async () => {
    process.env.TOOL_RUNTIME_TOKEN = "must-not-leak-into-the-child-process";
    try {
      const result = await runIsolated({ job: { kind: "env" } }, 10_000);
      const names = (result.names as string[]).filter((n) => !["PATH", "TMPDIR"].includes(n));
      // Bun may add its own runtime markers; none of the parent's variables may appear.
      expect(names.filter((n) => n in process.env)).toEqual([]);
      expect(result.names).not.toContain("TOOL_RUNTIME_TOKEN");
    } finally {
      delete process.env.TOOL_RUNTIME_TOKEN;
    }
  });

  test("runs a compute job and returns the outcome", async () => {
    const outcome = await runIsolated(
      {
        job: { kind: "compute", code: "return input.a * input.b;", input: { a: 6, b: 7 } },
        config,
      },
      10_000,
    );
    expect(outcome).toMatchObject({ ok: true, result: 42 });
  });

  test("the guest cannot reach host APIs even inside the child", async () => {
    const outcome = await runIsolated(
      {
        job: {
          kind: "compute",
          code: `return [typeof fetch, typeof process, typeof Bun, typeof require, Object.keys(globalThis).sort()];`,
          input: null,
        },
        config,
      },
      10_000,
    );
    const [fetchType, processType, bunType, requireType, globals] = outcome.result as [
      string,
      string,
      string,
      string,
      string[],
    ];
    expect([fetchType, processType, bunType, requireType]).toEqual([
      "undefined",
      "undefined",
      "undefined",
      "undefined",
    ]);
    expect(globals).toContain("input");
    expect(globals).not.toContain("process");
  });

  test("kills a child that outlives the whole-job deadline", async () => {
    // A script deadline above the job deadline: only the parent's kill can stop it.
    const started = performance.now();
    await expect(
      runIsolated(
        {
          job: { kind: "compute", code: "while (true) {}", input: null },
          config: { ...config, timeout_ms: 30_000 },
        },
        1_500,
      ),
    ).rejects.toMatchObject({ code: "TIMEOUT" });
    expect(performance.now() - started).toBeLessThan(5_000);
  });
});

// Confinement needs landrun (`bun run build:landrun`) and a kernel with Landlock. Where either
// is missing the runtime runs children unconfined, and these tests have nothing to check.
const enforced = (await runIsolated({ job: { kind: "confinement" } }, 10_000)) as {
  files: boolean;
  tcp: boolean;
};

describe("confinement", () => {
  /** Runs a script the way a job's child runs, with exactly that job's file access. */
  async function asChildOf(
    job: Parameters<typeof confinement>[0],
    directory: string,
    script: string,
  ): Promise<Record<string, string>> {
    const child = Bun.spawn(
      [...confinement(job, directory), process.execPath, "-e", script],
      {
        cwd: new URL("..", import.meta.url).pathname,
        env: { PATH: process.env.PATH ?? "", TMPDIR: directory },
        stdout: "pipe",
        stderr: "ignore",
      },
    );
    return JSON.parse(await new Response(child.stdout).text());
  }

  test.skipIf(!enforced.files)(
    "a child reaches its own job's files and nothing of another job's",
    async () => {
      const root = await mkdtemp(join(tmpdir(), "eneo-confinement-test-"));
      try {
        const own = join(root, "own");
        const mine = join(root, "cache-mine");
        const theirs = join(root, "cache-theirs");
        for (const directory of [own, mine, theirs])
          await Bun.write(join(directory, "0.csv"), "id\n1\n");
        const script = `
          const fs = require("node:fs");
          const attempt = (run) => { try { run(); return "ok"; } catch (e) { return e.code ?? "failed"; } };
          let tcp = "ok";
          try { Bun.listen({ hostname: "127.0.0.1", port: 0, socket: { data() {} } }).stop(true); } catch { tcp = "denied"; }
          console.log(JSON.stringify({
            readDeclared: attempt(() => fs.readFileSync(${JSON.stringify(join(mine, "0.csv"))})),
            writeDeclared: attempt(() => fs.writeFileSync(${JSON.stringify(join(mine, "0.csv"))}, "x")),
            writeOwn: attempt(() => fs.writeFileSync(${JSON.stringify(join(own, "scratch"))}, "x")),
            readOther: attempt(() => fs.readFileSync(${JSON.stringify(join(theirs, "0.csv"))})),
            listOther: attempt(() => fs.readdirSync(${JSON.stringify(theirs)})),
            listTmp: attempt(() => fs.readdirSync(${JSON.stringify(tmpdir())})),
            parentEnvironment: attempt(() => fs.readFileSync("/proc/" + process.ppid + "/environ")),
            spawn: attempt(() => { if (!Bun.spawnSync(["/bin/true"]).success) throw { code: "EACCES" }; }),
            tcp,
          }));`;
        const job = {
          job: {
            kind: "tabular_query" as const,
            csvPath: join(mine, "0.csv"),
            tables: [],
            statements: ["SELECT 1"],
            explain: false,
            config: tabularConfigSchema.parse({}),
          },
        };
        expect(await asChildOf(job, own, script)).toEqual({
          readDeclared: "ok",
          writeDeclared: "EACCES",
          writeOwn: "ok",
          readOther: "EACCES",
          listOther: "EACCES",
          listTmp: "EACCES",
          parentEnvironment: "EACCES",
          spawn: "EACCES",
          tcp: enforced.tcp ? "denied" : "ok",
        });
      } finally {
        await rm(root, { recursive: true, force: true });
      }
    },
  );

  test("a child that must be confined refuses its job when it is not", async () => {
    const directory = await mkdtemp(join(tmpdir(), "eneo-confinement-test-"));
    try {
      await writeFile(join(directory, "marker"), "");
      // No launcher: the child starts unconfined and has to notice that for itself.
      const child = Bun.spawn(
        [process.execPath, new URL("../src/child.ts", import.meta.url).pathname, REQUIRE_CONFINEMENT],
        {
          env: { PATH: process.env.PATH ?? "", TMPDIR: directory },
          stdin: new Blob([JSON.stringify({ job: { kind: "env" } })]),
          stdout: "pipe",
          stderr: "ignore",
        },
      );
      expect(JSON.parse(await new Response(child.stdout).text())).toMatchObject({
        ok: false,
        error: { code: "CONFINEMENT_UNAVAILABLE" },
      });
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  });

  test.skipIf(!enforced.files)("a confined job still passes when confinement is required", async () => {
    const outcome = await runIsolated(
      { job: { kind: "compute", code: "return 1 + 1;", input: null }, config },
      10_000,
      { requireConfinement: true },
    );
    expect(outcome).toMatchObject({ ok: true, result: 2 });
  });
});

describe("concurrency limit", () => {
  test("never runs more than the slot count at once", async () => {
    const limit = concurrencyLimit(2);
    let running = 0;
    let peak = 0;
    const task = async () => {
      running++;
      peak = Math.max(peak, running);
      await Bun.sleep(5);
      running--;
    };
    await Promise.all(Array.from({ length: 10 }, () => limit(task)));
    expect(peak).toBe(2);
  });
});
