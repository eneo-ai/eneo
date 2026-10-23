import { expect, it } from "vitest";
import { analysisStep } from "./analysisStep";
const call = { is_bundled: true, purpose: "file_analysis", tool_name: "query_table" };
it("identifies inspection and validation without model requests", () => {
  expect(analysisStep({ ...call, tool_name: "inspect_table" })?.kind).toBe("inspect");
  expect(analysisStep({ ...call, tool_name: "assert_table" })?.kind).toBe("check");
});
it("describes aggregates by their simple outer grouping columns", () => {
  expect(
    analysisStep(call, {
      sql: 'SELECT "Månad", SUM(budget) FROM t GROUP BY "Månad" ORDER BY "Månad"'
    })
  ).toEqual({ kind: "sum", groups: ["Månad"] });
  expect(
    analysisStep(call, { sql: 'SELECT t."Förvaltning", COUNT(*) FROM t GROUP BY t."Förvaltning";' })
  ).toEqual({ kind: "count", groups: ["Förvaltning"] });
});
it("ignores strings, comments and inner query groups", () => {
  expect(
    analysisStep(call, {
      sql: "WITH summary AS (SELECT SUM(x) FROM t GROUP BY secret) SELECT * FROM summary WHERE note = 'SUM(x) GROUP BY hidden' -- GROUP BY wrong"
    })
  ).toEqual({ kind: "query", groups: [] });
});
it.each(["1", "date_trunc('month', date)", "ALL", "a + b", "a, b, c, d"])(
  "does not guess the meaning of GROUP BY %s",
  (group) => {
    expect(analysisStep(call, { sql: `SELECT SUM(x) FROM t GROUP BY ${group}` })).toEqual({
      kind: "sum",
      groups: []
    });
  }
);
it("keeps external-provider labels and handles absent arguments", () => {
  expect(analysisStep({ ...call, is_bundled: false }, { sql: "SELECT SUM(x) FROM t" })).toBeNull();
  expect(analysisStep(call)).toEqual({ kind: "query", groups: [] });
});
