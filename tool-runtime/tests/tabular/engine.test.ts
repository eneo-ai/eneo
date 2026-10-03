import { beforeAll, afterAll, describe, expect, test } from "bun:test";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describeCsv, runQuery } from "../../src/tools/tabular/engine/duckdb";

let directory: string;
let csvPath: string;
beforeAll(async () => {
  directory = await mkdtemp(join(tmpdir(), "eneo-engine-test-"));
  csvPath = join(directory, "data.csv");
  await writeFile(csvPath, "department,value\nA,10\nA,20\nB,30\n");
});
afterAll(async () => {
  await rm(directory, { recursive: true, force: true });
});
describe("extracted DuckDB engine", () => {
  test("inspects schema, samples and value profiles", async () => {
    const data = await describeCsv(csvPath);
    expect(data.rowCount).toBe(3);
    expect(data.columns[0]?.profile?.values).toEqual(["A", "B"]);
  });
  test("aggregates, accepts a trailing semicolon, and reports truncation", async () => {
    const data = await runQuery({ csvPath, sql: "SELECT sum(value) FROM t;" });
    expect(String(data.rows[0]?.[0])).toBe("60");
    expect(data.parsedRows).toBe(3);
    const capped = await runQuery({ csvPath, sql: "SELECT * FROM t", rowLimit: 1 });
    expect(capped.returnedRows).toBe(1);
    expect(capped.truncated).toBe(true);
  });
  test("explains SELECT statements", async () => {
    const data = await runQuery({ csvPath, sql: "SELECT * FROM t", explainOnly: true });
    expect(data.rows.length).toBeGreaterThan(0);
  });
  for (const sql of [
    "SELECT 1; SELECT 2",
    "DROP TABLE t",
    "COPY t TO '/tmp/leaked.csv'",
    "ATTACH '/tmp/x.db'",
    "SET enable_external_access = true",
    "INSTALL httpfs",
    "PRAGMA version",
    "SELECT * FROM read_csv_auto('/etc/passwd')",
    "SELECT * FROM read_csv_auto('https://example.com/private.csv')",
    "SELECT * FROM glob('/tmp/*')",
  ]) {
    test(`rejects privileged SQL: ${sql}`, async () => {
      await expect(runQuery({ csvPath, sql })).rejects.toThrow();
    });
  }
  test("interrupts expensive queries and accepts the next query", async () => {
    await expect(
      runQuery({
        csvPath,
        sql: "SELECT SUM(a.i*b.i) FROM range(1000000000) a(i), range(1000000000) b(i)",
        timeoutMs: 50,
      }),
    ).rejects.toThrow();
    expect((await runQuery({ csvPath, sql: "SELECT true" })).rows).toEqual([[true]]);
  });
  test("joins extra aliased tables and rejects bad aliases", async () => {
    const extra = join(directory, "extra.csv");
    await writeFile(extra, "department,name\nA,Alpha\nB,Beta\n");
    const joined = await runQuery({
      csvPath,
      sql: "SELECT d.name, SUM(t.value) AS total FROM t JOIN d USING (department) GROUP BY 1 ORDER BY 1",
      tables: [{ alias: "d", csvPath: extra }],
    });
    expect(joined.rows.map((r) => [r[0], String(r[1])])).toEqual([
      ["Alpha", "30"],
      ["Beta", "30"],
    ]);
    for (const alias of ["t", "Bad", "1x", "a;b"])
      await expect(
        runQuery({ csvPath, sql: "SELECT 1", tables: [{ alias, csvPath: extra }] }),
      ).rejects.toThrow();
  });
  test("reports malformed CSV coverage", async () => {
    const malformed = join(directory, "malformed.csv");
    await writeFile(malformed, "a,b\n1,2\n3,4\n5,6,7\n8,9\n");
    const data = await runQuery({ csvPath: malformed, sql: "SELECT * FROM t" });
    expect(data.rejectedRows).toBeGreaterThan(0);
  });
});
