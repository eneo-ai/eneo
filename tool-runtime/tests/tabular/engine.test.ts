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
    const capped = await runQuery({
      csvPath,
      sql: "SELECT * FROM t",
      rowLimit: 1,
    });
    expect(capped.returnedRows).toBe(1);
    expect(capped.truncated).toBe(true);
  });
  test("explains SELECT statements", async () => {
    const data = await runQuery({
      csvPath,
      sql: "SELECT * FROM t",
      explainOnly: true,
    });
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
    expect((await runQuery({ csvPath, sql: "SELECT true" })).rows).toEqual([
      [true],
    ]);
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
        runQuery({
          csvPath,
          sql: "SELECT 1",
          tables: [{ alias, csvPath: extra }],
        }),
      ).rejects.toThrow();
  });
  test("reports malformed CSV coverage", async () => {
    const malformed = join(directory, "malformed.csv");
    await writeFile(malformed, "a,b\n1,2\n3,4\n5,6,7\n8,9\n");
    const data = await runQuery({ csvPath: malformed, sql: "SELECT * FROM t" });
    expect(data.rejectedRows).toBeGreaterThan(0);
  });
  test("types every column from the whole file, so a late non-numeric value loses no row", async () => {
    const late = join(directory, "late.csv");
    const lines = ["id,amount,code"];
    for (let i = 1; i <= 25_000; i++) lines.push(`${i},${i * 3},K-${i}`);
    lines.push("25001,N/A,K-25001", "25002,12,K-25002");
    await writeFile(late, lines.join("\n") + "\n");
    const described = await describeCsv(late);
    expect(described.columns[1]).toMatchObject({ type: "VARCHAR" });
    expect(described.columns[1]!.profile!.hint).toContain("TRY_CAST(");
    expect(described.columns[2]!.profile!.examples).toHaveLength(3);
    expect([described.rowCount, described.rejectedRows]).toEqual([25_002, 0]);
    const queried = await runQuery({
      csvPath: late,
      sql: "SELECT COUNT(*), SUM(TRY_CAST(amount AS DOUBLE)) FROM t",
    });
    expect([queried.parsedRows, queried.rejectedRows]).toEqual([25_002, 0]);
    expect(Number(queried.rows[0]![0])).toBe(25_002);
  });
  test("skips report titles above the header and keeps every row of a header-less file", async () => {
    const titled = join(directory, "titled.csv");
    await writeFile(
      titled,
      "Rapport budgetutfall 2024,,\n,,\nKommun,Belopp,Ar\nSundsvall,100,2024\nTimra,200,2024\n",
    );
    const described = await describeCsv(titled);
    expect(described.skipRows).toBe(2);
    expect(described.columns.map((c) => [c.name, c.type])).toEqual([
      ["Kommun", "VARCHAR"],
      ["Belopp", "BIGINT"],
      ["Ar", "BIGINT"],
    ]);
    expect(described.rowCount).toBe(2);
    const queried = await runQuery({
      csvPath: titled,
      skipRows: 2,
      sql: "SELECT SUM(Belopp) FROM t",
    });
    expect(String(queried.rows[0]![0])).toBe("300");

    const headless = join(directory, "headless.csv");
    await writeFile(headless, "1,2\n3,4\n5,6\n");
    const plain = await describeCsv(headless);
    expect(plain.skipRows).toBeUndefined();
    expect(plain.rowCount).toBe(3);
  });
  test("tells how to cast text that holds locally formatted numbers and dates", async () => {
    const swedish = join(directory, "swedish.csv");
    await writeFile(
      swedish,
      "Kommun;Belopp;Andel;Datum\nSundsvall;1 234,50;12,5%;31.12.2024\nTimrå;987,25;7,0%;01.01.2025\nÅnge;15 000,00;3,2%;15.06.2024\n",
    );
    const { columns } = await describeCsv(swedish);
    const profile = (name: string) =>
      columns.find((c) => c.name === name)!.profile!;
    expect(profile("Kommun").hint).toBeUndefined();
    expect(profile("Belopp").hint).toContain("TRY_CAST(REPLACE(");
    expect(profile("Andel").hint).toContain("percent");
    // Day-first dates are typed by the sniffer itself and need no hint.
    expect(columns.find((c) => c.name === "Datum")).toMatchObject({
      type: "DATE",
    });
    expect(profile("Datum").hint).toBeUndefined();
    const cast = await runQuery({
      csvPath: swedish,
      sql: `SELECT SUM(TRY_CAST(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE("Belopp", ' ', ''), chr(160), ''), '.', ''), '%', ''), ',', '.') AS DOUBLE)) FROM t`,
    });
    expect(Number(cast.rows[0]![0])).toBeCloseTo(17_221.75);
  });
});
