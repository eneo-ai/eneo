import { afterAll, describe, expect, test } from "bun:test";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { readSource } from "../../src/tools/documents/sources";

const directory = await mkdtemp(join(tmpdir(), "sources-test-"));
afterAll(() => rm(directory, { recursive: true, force: true }));

describe("source files", () => {
  test("keep dates and timestamps in ISO form, whatever the host's time zone", async () => {
    const path = join(directory, "dates.csv");
    await writeFile(path, "Datum,Tid\n2026-09-01,2026-09-02 12:30:00\n");
    const { rows } = await readSource({ index: 0, path, isXlsx: false });
    expect(rows).toEqual([["2026-09-01", "2026-09-02T12:30:00.000Z"]]);
  });
});
