import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { mkdtemp, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import ExcelJS from "exceljs";
import { createHandler } from "../../src/server";
import { runIsolated } from "../../src/sandbox";
import { SheetCache } from "../../src/tools/tabular/cache";
import { tabularConfigSchema } from "../../src/tools/tabular/config";
import type { downloadFile } from "../../src/tools/tabular/download";
import { executeIngest, executeQuery, toCsv } from "../../src/tools/tabular/execute";
import type { QueryJobResult, SheetMetadata } from "../../src/tools/tabular/ports";
import { exportFilename, tabularTools, type TabularExecutor } from "../../src/tools/tabular/tool";
import { RichResult, type CallContext, type ToolDefinition } from "../../src/tools/types";

const ORIGIN = "http://backend:8000";
const FILE_A = "11111111-1111-4111-8111-111111111111";
const FILE_B = "22222222-2222-4222-8222-222222222222";
const alice: CallContext = {
  tenantId: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  userId: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  fileOrigin: ORIGIN,
};
const bob: CallContext = { ...alice, userId: "cccccccc-cccc-4ccc-8ccc-cccccccccccc" };
const config = tabularConfigSchema.parse({});
const url = (id: string, token = "signed") =>
  `${ORIGIN}/api/v1/files/${id}/original/download/?token=${token}`;

const SALES = Buffer.from("region,amount\nnorth,100\nsouth,250.5\nnorth,50\n");
let workbook: Buffer;
let root: string;

beforeAll(async () => {
  root = await mkdtemp(join(tmpdir(), "tabular-tool-test-"));
  const book = new ExcelJS.Workbook();
  const budget = book.addWorksheet("Budget");
  budget.addRow(["region", "budget"]);
  budget.addRow(["north", 120]);
  budget.addRow(["south", 200]);
  const notes = book.addWorksheet("Notes");
  notes.addRow(["note"]);
  notes.addRow(["draft"]);
  workbook = Buffer.from(await book.xlsx.writeBuffer());
});
afterAll(() => rm(root, { recursive: true, force: true }));

type Downloads = { calls: string[]; denied: Set<string> };
function setup(
  dir: string,
  allowedFileOrigins: string[] = [],
  limits: Partial<typeof config> = {},
) {
  const downloads: Downloads = { calls: [], denied: new Set() };
  const ingests: string[] = [];
  const download = (async (raw: string) => {
    downloads.calls.push(raw);
    const token = new URL(raw).searchParams.get("token")!;
    if (downloads.denied.has(token)) throw Object.assign(new Error("response:403"));
    return raw.includes(FILE_B)
      ? {
          bytes: workbook,
          contentType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          name: "budget.xlsx",
        }
      : { bytes: SALES, contentType: "text/csv", name: "sales.csv" };
  }) as unknown as typeof downloadFile;
  // In-process executor: the sandbox boundary has its own test below.
  const executor: TabularExecutor = {
    async ingest(job) {
      ingests.push(job.inputPath);
      return executeIngest(job);
    },
    query: (job) => executeQuery(job),
  };
  const tools = tabularTools({
    config: { ...config, ...limits },
    allowedFileOrigins,
    cache: new SheetCache(join(root, dir), config.cache_ttl_ms, config.cache_max_bytes),
    executor,
    download,
  });
  const tool = (name: string) => tools.find((t) => t.name === name) as ToolDefinition;
  return { tool, downloads, ingests };
}

describe("file references", () => {
  test("only signed Eneo download URLs at the configured origin are fetched", async () => {
    const { tool, downloads } = setup("refs");
    for (const bad of [
      `https://evil.example/api/v1/files/${FILE_A}/original/download/?token=x`,
      `${ORIGIN}/api/v1/files/${FILE_A}/original/download/`,
      `${ORIGIN}/api/v1/users/me/?token=x`,
      `${ORIGIN}/api/v1/files/${FILE_A}/original/download/../../../users/?token=x`,
      "file:///etc/passwd",
    ])
      await expect(
        tool("inspect_table").execute({ files: [{ url: bad, filename: "a.csv" }] }, alice),
      ).rejects.toMatchObject({ code: "INVALID_URL" });
    expect(downloads.calls).toEqual([]);
  });

  test("fetches only from the file origin Eneo sent", async () => {
    const { tool, downloads } = setup("origin");
    const inspect = (ctx: CallContext) =>
      tool("inspect_table").execute({ files: [{ url: url(FILE_A), filename: "a.csv" }] }, ctx);
    await expect(inspect({ ...alice, fileOrigin: undefined })).rejects.toMatchObject({
      code: "FILE_ORIGIN_UNKNOWN",
    });
    // The model's URL must match Eneo's origin, not merely look like an Eneo link.
    await expect(inspect({ ...alice, fileOrigin: "http://other:8000" })).rejects.toMatchObject({
      code: "INVALID_URL",
    });
    expect(downloads.calls).toEqual([]);
    await inspect(alice);
    expect(downloads.calls).toHaveLength(1);
  });

  test("a link copied from history explains itself instead of failing as expired", async () => {
    const { tool, downloads } = setup("stale");
    await expect(
      tool("inspect_table").execute(
        { files: [{ url: url(FILE_A, "REDACTED"), filename: "a.csv" }] },
        alice,
      ),
    ).rejects.toMatchObject({ code: "STALE_REFERENCE" });
    expect(downloads.calls).toEqual([]);
  });

  test("an operator allowlist also bounds Eneo's origin", async () => {
    const { tool, downloads } = setup("allowlist", ["http://backend:9000"]);
    await expect(
      tool("inspect_table").execute({ files: [{ url: url(FILE_A), filename: "a.csv" }] }, alice),
    ).rejects.toMatchObject({ code: "FILE_ORIGIN_NOT_ALLOWED" });
    expect(downloads.calls).toEqual([]);
  });

  test("rejects unsupported file types before downloading", async () => {
    const { tool, downloads } = setup("types");
    await expect(
      tool("inspect_table").execute({ files: [{ url: url(FILE_A), filename: "a.json" }] }, alice),
    ).rejects.toThrow();
    expect(downloads.calls).toEqual([]);
  });
});

describe("inspect and query", () => {
  test("inspects every sheet of a workbook", async () => {
    const { tool } = setup("inspect");
    const result = (await tool("inspect_table").execute(
      { files: [{ url: url(FILE_B), filename: "budget.xlsx" }] },
      alice,
    )) as { files: Array<{ sheets: Array<{ name: string; parsed_rows: number }> }> };
    expect(result.files[0]!.sheets.map((s) => [s.name, s.parsed_rows])).toEqual([
      ["Budget", 2],
      ["Notes", 1],
    ]);
  });

  test("computes exact totals over the whole file", async () => {
    const { tool } = setup("totals");
    const result = await tool("query_table").execute(
      {
        file: { url: url(FILE_A), filename: "sales.csv" },
        sql: "SELECT region, SUM(amount) AS total FROM t GROUP BY region ORDER BY region;",
      },
      alice,
    );
    expect(result).toMatchObject({
      columns: ["region", "total"],
      rows: [
        ["north", 150],
        ["south", 250.5],
      ],
      truncated: false,
      parsed_rows: 3,
      rejected_rows: 0,
    });
  });

  test("joins two attachments and requires a sheet for multi-sheet workbooks", async () => {
    const { tool } = setup("join");
    const call = (sheet?: string) =>
      tool("query_table").execute(
        {
          file: { url: url(FILE_A), filename: "sales.csv" },
          files: [
            {
              url: url(FILE_B),
              filename: "budget.xlsx",
              alias: "budget",
              ...(sheet ? { sheet } : {}),
            },
          ],
          sql: "SELECT t.region, SUM(t.amount) - ANY_VALUE(b.budget) AS over FROM t JOIN budget b USING (region) GROUP BY t.region ORDER BY 1",
        },
        alice,
      );
    await expect(call()).rejects.toMatchObject({ code: "SHEET_REQUIRED" });
    await expect(call("Nope")).rejects.toMatchObject({ code: "UNKNOWN_SHEET" });
    expect(await call("Budget")).toMatchObject({
      rows: [
        ["north", 30],
        ["south", 50.5],
      ],
    });
  });

  test("reports checks individually", async () => {
    const { tool } = setup("assert");
    const result = await tool("assert_table").execute(
      {
        file: { url: url(FILE_A), filename: "sales.csv" },
        checks: [
          { name: "no missing amounts", sql: "SELECT COUNT(*) = 0 FROM t WHERE amount IS NULL" },
          { name: "unique regions", sql: "SELECT COUNT(*) = COUNT(DISTINCT region) FROM t" },
          { name: "broken", sql: "DROP TABLE t" },
        ],
      },
      alice,
    );
    expect(result).toMatchObject({
      passed: false,
      checks: [
        { name: "no missing amounts", passed: true },
        { name: "unique regions", passed: false, value: false },
        { name: "broken", passed: false },
      ],
    });
  });

  test("rejects anything but one SELECT", async () => {
    const { tool } = setup("reject");
    for (const sql of [
      "COPY t TO '/tmp/out.csv'",
      "SELECT 1; SELECT 2",
      "SELECT * FROM read_csv_auto('/etc/passwd')",
      "ATTACH '/tmp/x.db'",
    ])
      await expect(
        tool("query_table").execute(
          { file: { url: url(FILE_A), filename: "sales.csv" }, sql },
          alice,
        ),
      ).rejects.toMatchObject({ code: "QUERY_REJECTED" });
  });
});

describe("export", () => {
  test("the full result becomes a CSV file while the inline rows stay a preview", async () => {
    const { tool } = setup("export", [], { row_limit: 1, export_row_limit: 10 });
    const result = await tool("query_table").execute(
      {
        file: { url: url(FILE_A), filename: "sales.csv" },
        sql: "SELECT region, amount FROM t ORDER BY amount",
        export: true,
        export_filename: "Försäljning/2026",
      },
      alice,
    );

    expect(result).toBeInstanceOf(RichResult);
    const { structured, files } = result as RichResult;
    expect(structured).toMatchObject({
      returned_rows: 1,
      truncated: true,
      export: { filename: "Försäljning2026.csv", rows: 3, truncated: false },
    });
    expect(files[0]!.mimeType).toBe("text/csv");
    expect(Buffer.from(files[0]!.blob, "base64").toString()).toBe(
      "region,amount\r\nnorth,50\r\nnorth,100\r\nsouth,250.5\r\n",
    );
  });

  test("an export at its row limit says so", async () => {
    const { tool } = setup("export-limit", [], { export_row_limit: 2 });
    const { structured } = (await tool("query_table").execute(
      { file: { url: url(FILE_A), filename: "sales.csv" }, sql: "SELECT * FROM t", export: true },
      alice,
    )) as RichResult;
    expect(structured).toMatchObject({ export: { rows: 2, truncated: true } });
  });

  test("CSV quoting round-trips commas, quotes, newlines and nulls", () => {
    expect(
      toCsv(
        ["a", "b"],
        [
          ["x,y", 'say "hi"'],
          ["line\nbreak", null],
          [1.5, true],
        ],
      ),
    ).toBe('a,b\r\n"x,y","say ""hi"""\r\n"line\nbreak",\r\n1.5,true\r\n');
    expect(exportFilename(undefined)).toBe("resultat.csv");
    expect(exportFilename("../x.csv")).toBe("x.csv");
  });
});

describe("cache", () => {
  test("re-downloads on every call and parses once per user", async () => {
    const { tool, downloads, ingests } = setup("cache");
    const query = (ctx: CallContext) =>
      tool("query_table").execute(
        { file: { url: url(FILE_A), filename: "sales.csv" }, sql: "SELECT COUNT(*) FROM t" },
        ctx,
      );
    await query(alice);
    await query(alice);
    expect(downloads.calls).toHaveLength(2);
    expect(ingests).toHaveLength(1);
    // Another user with the same bytes gets their own entry.
    await query(bob);
    expect(ingests).toHaveLength(2);
  });

  test("a cached file is not served once Eneo refuses the download", async () => {
    const { tool, downloads } = setup("revoked");
    const file = (token: string) => ({ url: url(FILE_A, token), filename: "sales.csv" });
    await tool("inspect_table").execute({ files: [file("ok")] }, alice);
    downloads.denied.add("revoked");
    await expect(
      tool("inspect_table").execute({ files: [file("revoked")] }, alice),
    ).rejects.toThrow();
  });

  test("expired entries are rebuilt and evicted", async () => {
    const dir = join(root, "expiry");
    const cache = new SheetCache(dir, 0, config.cache_max_bytes);
    let builds = 0;
    const build = async () => {
      builds++;
      return [] as SheetMetadata[];
    };
    await cache.getOrBuild("k", build);
    await Bun.sleep(5);
    await cache.getOrBuild("k", build);
    expect(builds).toBe(2);
    await Bun.sleep(5);
    await cache.evict();
    expect(await readdir(dir)).toEqual([]);
  });

  test("an idle runtime still removes expired entries from disk", async () => {
    const dir = join(root, "sweep");
    const cache = new SheetCache(dir, 20, config.cache_max_bytes);
    await cache.getOrBuild("k", async () => [] as SheetMetadata[]);
    expect(await readdir(dir)).toHaveLength(1);
    const timer = cache.sweepEvery(10);
    try {
      await Bun.sleep(100);
      expect(await readdir(dir)).toEqual([]);
    } finally {
      clearInterval(timer);
    }
  });
});

describe("sandbox", () => {
  test("ingest and query run in a child process with native DuckDB", async () => {
    const dir = await mkdtemp(join(root, "child-"));
    const input = join(dir, "original");
    await Bun.write(input, SALES);
    const { sheets } = (await runIsolated(
      {
        job: {
          kind: "tabular_ingest",
          inputPath: input,
          isXlsx: false,
          contentType: "text/csv",
          outputDir: dir,
          config,
        },
      },
      25_000,
    )) as { sheets: SheetMetadata[] };
    const { results } = (await runIsolated(
      {
        job: {
          kind: "tabular_query",
          csvPath: join(dir, sheets[0]!.csv),
          tables: [],
          statements: ["SELECT SUM(amount) FROM t", "SELECT * FROM read_csv_auto('/etc/passwd')"],
          explain: false,
          config,
        },
      },
      25_000,
    )) as unknown as QueryJobResult;
    expect(results[0]).toMatchObject({ ok: true, outcome: { rows: [[400.5]] } });
    expect(results[1]).toMatchObject({ ok: false, code: "QUERY_REJECTED" });
  });
});

describe("identity", () => {
  test("the tabular endpoint refuses calls without forwarded identity", async () => {
    const token = "t".repeat(40);
    const { tool } = setup("identity");
    const handler = createHandler({
      token,
      maxConcurrency: 2,
      endpoints: [
        {
          slug: "tabular",
          requiresIdentity: true,
          toolTimeoutMs: 30_000,
          tools: [tool("inspect_table")],
        },
      ],
    });
    const response = await handler(
      new Request("http://tool-runtime:3010/mcp/tabular", {
        method: "POST",
        headers: {
          authorization: `Bearer ${token}`,
          "content-type": "application/json",
          accept: "application/json, text/event-stream",
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: 1,
          method: "tools/call",
          params: {
            name: "inspect_table",
            arguments: { files: [{ url: url(FILE_A), filename: "a.csv" }] },
          },
        }),
      }),
    );
    const body = (await response.json()) as { result: { isError?: boolean; content: unknown } };
    expect(body.result.isError).toBe(true);
    expect(JSON.stringify(body.result.content)).toContain("IDENTITY_REQUIRED");
  });
});
