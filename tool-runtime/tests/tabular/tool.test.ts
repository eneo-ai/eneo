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
import { queryResultView } from "../../src/tools/tabular/view";
import {
  filterRows,
  pageSql,
  quoteIdentifier,
  sortRows,
  showsTable,
  toTsv,
} from "../../src/tools/tabular/view/paging";
import { RichResult, type CallContext, type ToolDefinition } from "../../src/tools/types";

const ORIGIN = "http://backend:8000";
const FILE_A = "11111111-1111-4111-8111-111111111111";
const FILE_B = "22222222-2222-4222-8222-222222222222";
const alice: CallContext = {
  tenantId: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  userId: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  fileOrigin: ORIGIN,
};
const bob: CallContext = {
  ...alice,
  userId: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
};
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
    )) as {
      files: Array<{ sheets: Array<{ name: string; parsed_rows: number }> }>;
    };
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
          {
            name: "no missing amounts",
            sql: "SELECT COUNT(*) = 0 FROM t WHERE amount IS NULL",
          },
          {
            name: "unique regions",
            sql: "SELECT COUNT(*) = COUNT(DISTINCT region) FROM t",
          },
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
    const { tool } = setup("export", [], {
      row_limit: 1,
      export_row_limit: 10,
    });
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
      {
        file: { url: url(FILE_A), filename: "sales.csv" },
        sql: "SELECT * FROM t",
        export: true,
      },
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
        {
          file: { url: url(FILE_A), filename: "sales.csv" },
          sql: "SELECT COUNT(*) FROM t",
        },
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
    const file = (token: string) => ({
      url: url(FILE_A, token),
      filename: "sales.csv",
    });
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
  test.each([undefined, { source_rows: [2, 4] }])(
    "ingest and query keep selection %j inside the sandbox",
    async (selection) => {
      const dir = await mkdtemp(join(root, "child-"));
      const input = join(dir, "original");
      await Bun.write(input, SALES);
      const { sheets } = (await runIsolated(
        {
          job: {
            kind: "tabular_ingest",
            selection: selection ? { source_rows: [...selection.source_rows] } : undefined,
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
            explicitHeader: sheets[0]!.explicitHeader,
            tables: [],
            statements: ["SELECT SUM(amount) FROM t", "SELECT * FROM read_csv_auto('/etc/passwd')"],
            explain: false,
            config,
          },
        },
        25_000,
      )) as unknown as QueryJobResult;
      expect(results[0]).toMatchObject({
        ok: true,
        outcome: { rows: [[selection ? "150" : 400.5]] },
      });
      expect(results[1]).toMatchObject({ ok: false, code: "QUERY_REJECTED" });
    },
  );
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
    const body = (await response.json()) as {
      result: { isError?: boolean; content: unknown };
    };
    expect(body.result.isError).toBe(true);
    expect(JSON.stringify(body.result.content)).toContain("IDENTITY_REQUIRED");
  });
});

describe("result view", () => {
  test("query_table brings a table view the host reads as a resource", async () => {
    const token = "t".repeat(40);
    const view = await queryResultView();
    const { tool } = setup("view");
    const handler = createHandler({
      token,
      maxConcurrency: 2,
      endpoints: [
        {
          slug: "file-analysis",
          toolTimeoutMs: 30_000,
          tools: [{ ...tool("query_table"), view }, tool("inspect_table")],
        },
      ],
    });
    const rpc = async (method: string, params: unknown) => {
      const response = await handler(
        new Request("http://tool-runtime:3010/mcp/file-analysis", {
          method: "POST",
          headers: {
            authorization: `Bearer ${token}`,
            "content-type": "application/json",
            accept: "application/json, text/event-stream",
          },
          body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
        }),
      );
      return ((await response.json()) as { result: Record<string, unknown> }).result;
    };

    const listed = (await rpc("tools/list", {})).tools as Array<Record<string, unknown>>;
    expect(listed.find((t) => t.name === "query_table")?._meta).toEqual({
      ui: { resourceUri: view.uri },
    });
    expect(listed.find((t) => t.name === "inspect_table")?._meta).toBeUndefined();

    expect(view.uri).toMatch(/^ui:\/\/file-analysis\/query-result-[0-9a-f]{12}\.html$/);
    const read = (await rpc("resources/read", { uri: view.uri })).contents as Array<
      Record<string, unknown>
    >;
    expect(read).toHaveLength(1);
    expect(read[0]).toMatchObject({
      uri: view.uri,
      mimeType: "text/html;profile=mcp-app",
      _meta: { ui: { permissions: { clipboardWrite: {} } } },
    });
    // The official SDK includes schema/documentation URLs as string literals.
    // The document still embeds its assets rather than loading remote scripts.
    expect(read[0]!.text).toContain('<div id="app"></div>');
    expect(read[0]!.text).not.toMatch(/<(?:script|link|img)\b[^>]*(?:src|href)=["']https?:\/\//i);
  });

  test("the view reads on from the model's query in pages and in another order", async () => {
    const { tool } = setup("view-pages");
    // As a model may leave it: a closing semicolon and a comment on the last line.
    const sql = "SELECT region, amount FROM t -- every sale\n;";
    const page = (await tool("query_table").execute(
      {
        file: { url: url(FILE_A), filename: "sales.csv" },
        sql: pageSql(sql, {
          limit: 2,
          offset: 1,
          order: { column: "amount", descending: true },
        }),
      },
      alice,
    )) as { columns: string[]; rows: unknown[][] };
    expect(page.columns).toEqual(["region", "amount"]);
    expect(page.rows).toEqual([
      ["north", 100],
      ["north", 50],
    ]);
  });

  test("the model is told when the rows are shown as a table, and only then", async () => {
    const view = await queryResultView();
    const tools = tabularTools({
      config,
      allowedFileOrigins: [],
      cache: new SheetCache(join(root, "view-note"), config.cache_ttl_ms, config.cache_max_bytes),
      executor: {
        ingest: (job) => executeIngest(job),
        query: (job) => executeQuery(job),
      },
      download: (async () => ({
        bytes: SALES,
        contentType: "text/csv",
        name: "sales.csv",
      })) as unknown as typeof downloadFile,
      resultView: view,
    });
    const query = tools.find((t) => t.name === "query_table") as ToolDefinition;
    const file = { url: url(FILE_A), filename: "sales.csv" };
    const shown = { ...alice, showsViews: true };

    const rows = (await query.execute({ file, sql: "SELECT * FROM t" }, shown)) as {
      shown?: string;
      rows: unknown[][];
    };
    expect(rows.shown).toContain("sees these rows as a table");

    // Chart preparation returns exactly the same data without claiming a visible table.
    const intermediate = (await query.execute(
      { file, sql: "SELECT * FROM t", display: "none" },
      shown,
    )) as { rows: unknown[][]; display: "none" };
    expect(intermediate.rows).toEqual(rows.rows);
    expect(intermediate.display).toBe("none");
    expect(intermediate).not.toHaveProperty("shown");
    expect(showsTable({ ...intermediate, plan: false, exported: false })).toBe(false);
    const explicitTable = await query.execute(
      { file, sql: "SELECT * FROM t", display: "table" },
      shown,
    );
    expect(explicitTable).toEqual(rows);
    expect(showsTable({ rows: rows.rows, plan: false, exported: false })).toBe(true);
    await expect(
      query.execute({ file, sql: "SELECT * FROM t", display: "invalid" }, shown),
    ).rejects.toThrow();

    // A single value has no table, and a host that shows no views is told nothing.
    const one = await query.execute({ file, sql: "SELECT COUNT(*) AS n FROM t" }, shown);
    expect(one).not.toHaveProperty("shown");
    const unseen = await query.execute({ file, sql: "SELECT * FROM t" }, alice);
    expect(unseen).not.toHaveProperty("shown");
    // A result delivered as a file is the file, not a table under the answer.
    const exported = (await query.execute(
      { file, sql: "SELECT * FROM t", export: true },
      shown,
    )) as RichResult;
    expect(exported.structured).not.toHaveProperty("shown");
  });

  test("a column name is quoted whatever it holds", () => {
    expect(quoteIdentifier('antal "st"')).toBe('"antal ""st"""');
  });

  test("rows held in full are sorted, filtered and copied in the view itself", () => {
    const rows = [
      ["b", 2],
      ["a", null],
      ["c", 10],
    ];
    expect(sortRows(rows, 1, false).map((r) => r[0])).toEqual(["b", "c", "a"]);
    expect(sortRows(rows, 1, true).map((r) => r[0])).toEqual(["c", "b", "a"]);
    expect(filterRows(rows, " C ")).toEqual([["c", 10]]);
    expect(toTsv(["name", "n"], [["two\nlines", null]])).toBe("name\tn\ntwo lines\t");
  });
});

describe("formula diagnostics across the workflow", () => {
  test("inspection, cached direct queries, joins, checks and exports retain source limitations", async () => {
    const book = new ExcelJS.Workbook();
    const sheet = book.addWorksheet("Budget");
    sheet.addRow(["region", "budget"]);
    sheet.addRow(["north", { formula: "100+20", result: 120 }]);
    sheet.addRow(["south", { formula: "100+100" }]);
    book.addWorksheet("No results").getCell("A1").value = { formula: "1+1" };
    const original = workbook;
    workbook = Buffer.from(await book.xlsx.writeBuffer());
    try {
      const { tool, ingests } = setup("formulas");
      const file = { url: url(FILE_B), filename: "budget.xlsx", sheet: "Budget" };
      // Direct queries must disclose limitations without a preceding inspection.
      const query = (await tool("query_table").execute(
        {
          file,
          sql: "SELECT SUM(budget) AS total FROM t",
        },
        alice,
      )) as any;
      expect(query.rows).toEqual([["120"]]);
      expect(query.calculation_warnings[0].missing_cached_results).toBe(1);
      const inspection = (await tool("inspect_table").execute(
        { files: [{ url: file.url, filename: file.filename }] },
        alice,
      )) as any;
      expect(inspection.files[0].sheets[0].calculation.formula_cells).toBe(2);
      expect(inspection.files[0].sheets[1].queryable).toBe(false);
      expect(inspection.files[0].sheets[1].calculation.missing_cached_results).toBe(1);
      expect(ingests.length).toBe(1);
      const joined = (await tool("query_table").execute(
        {
          file: { url: url(FILE_A), filename: "sales.csv" },
          files: [{ ...file, alias: "budget" }],
          sql: "SELECT SUM(t.amount) FROM t JOIN budget ON t.region = budget.region",
        },
        alice,
      )) as any;
      expect(joined.calculation_warnings[0].filename).toBe("budget.xlsx");
      const checks = (await tool("assert_table").execute(
        {
          file,
          checks: [{ name: "Rows present", sql: "SELECT COUNT(*) > 0 FROM t" }],
        },
        alice,
      )) as any;
      expect(checks.passed).toBe(true);
      expect(checks.calculation_warnings[0].missing_cached_results).toBe(1);
      const exported = (await tool("query_table").execute(
        {
          file,
          sql: "SELECT * FROM t",
          export: true,
        },
        alice,
      )) as any;
      expect(exported.structured.calculation_warnings[0].missing_cached_results).toBe(1);
      expect(exported.files.length).toBe(1);
      await expect(
        tool("query_table").execute(
          {
            file: { ...file, sheet: "No results" },
            sql: "SELECT * FROM t",
          },
          alice,
        ),
      ).rejects.toThrow("no queryable values");
    } finally {
      workbook = original;
    }
  });
});

describe("native source-row selections", () => {
  test("filters before aggregation, sorting, limits, joins and exports without polluting full-file cache", async () => {
    const { tool, downloads, ingests } = setup("selected-csv");
    const file = { url: url(FILE_A), filename: "sales.csv", source_rows: [4, 2, 4] };
    const inspection = (await tool("inspect_table").execute({ files: [file] }, alice)) as any;
    expect(inspection.files[0].sheets[0].source_rows).toEqual([2, 4]);
    expect(inspection.files[0].sheets[0].parsed_rows).toBe(2);
    const total = (await tool("query_table").execute(
      { file, sql: "SELECT SUM(amount) AS total FROM t" },
      alice,
    )) as any;
    expect(Number(total.rows[0][0])).toBe(150);
    const largest = (await tool("query_table").execute(
      { file, sql: "SELECT amount FROM t ORDER BY amount DESC LIMIT 1" },
      alice,
    )) as any;
    expect(Number(largest.rows[0][0])).toBe(100);
    const exported = (await tool("query_table").execute(
      { file, sql: "SELECT * FROM t", export: true },
      alice,
    )) as any;
    expect(exported.structured.returned_rows).toBe(2);
    expect(exported.structured.source_rows).toEqual([2, 4]);
    const all = (await tool("query_table").execute(
      { file: { url: file.url, filename: file.filename }, sql: "SELECT SUM(amount) FROM t" },
      alice,
    )) as any;
    expect(Number(all.rows[0][0])).toBe(400.5);
    const joined = (await tool("query_table").execute(
      {
        file,
        files: [{ url: file.url, filename: file.filename, source_rows: [2], alias: "chosen" }],
        sql: "SELECT SUM(t.amount) FROM t JOIN chosen USING (region)",
      },
      alice,
    )) as any;
    expect(Number(joined.rows[0][0])).toBe(150);
    const checks = (await tool("assert_table").execute(
      { file, checks: [{ name: "selection", sql: "SELECT COUNT(*) = 2 FROM t" }] },
      alice,
    )) as any;
    expect(checks.passed).toBe(true);
    expect(ingests.length).toBe(3);
    downloads.denied.add("revoked");
    await expect(
      tool("query_table").execute(
        { file: { ...file, url: url(FILE_A, "revoked") }, sql: "SELECT * FROM t" },
        alice,
      ),
    ).rejects.toThrow();
  });

  test("uses original worksheet row numbers despite blank rows, duplicate values and formulas", async () => {
    const original = workbook;
    const book = new ExcelJS.Workbook();
    const sheet = book.addWorksheet("Budget");
    sheet.addRow(["region", "budget"]);
    sheet.addRow(["same", 10]);
    sheet.addRow([]);
    sheet.addRow(["same", 90]);
    sheet.addRow(["zero", { formula: "1-1", result: 0 }]);
    sheet.addRow(["missing", { formula: "1+1" }]);
    workbook = Buffer.from(await book.xlsx.writeBuffer());
    try {
      const { tool } = setup("selected-xlsx");
      const file = {
        url: url(FILE_B),
        filename: "budget.xlsx",
        sheet: "Budget",
        source_rows: [3, 4, 5, 6],
      };
      const output = (await tool("query_table").execute(
        { file, sql: "SELECT * FROM t" },
        alice,
      )) as any;
      expect(output.rows).toEqual([
        [null, null],
        ["same", "90"],
        ["zero", "0"],
        ["missing", null],
      ]);
      expect(output.source_rows).toEqual([3, 4, 5, 6]);
      expect(output.calculation_warnings[0].formula_cells).toBe(2);
      expect(output.calculation_warnings[0].missing_cached_results).toBe(1);
      await expect(
        tool("query_table").execute(
          { file: { ...file, source_rows: [7] }, sql: "SELECT * FROM t" },
          alice,
        ),
      ).rejects.toThrow("outside");
      await expect(
        tool("query_table").execute(
          { file: { ...file, sheet: "Other" }, sql: "SELECT * FROM t" },
          alice,
        ),
      ).rejects.toThrow("worksheet");
    } finally {
      workbook = original;
    }
  });

  test("rejects invalid selectors rather than widening to the full table", async () => {
    const { tool } = setup("invalid-selection");
    for (const rows of [[], [1], [2.5], [-1], [999999999], Array(501).fill(2)]) {
      await expect(
        tool("query_table").execute(
          {
            file: { url: url(FILE_A), filename: "sales.csv", source_rows: rows },
            sql: "SELECT * FROM t",
          },
          alice,
        ),
      ).rejects.toThrow();
    }
  });
});
