/**
 * The SQL the result view runs to read its own query again: another page of it, or the same
 * rows in another order. The view only ever wraps the query the model wrote; the wrapped
 * statement goes through query_table like any other and is checked there.
 */

export type SortOrder = { column: string; descending: boolean };

/**
 * Whether the view has a table to show for a result. A single row, a query plan and a result
 * delivered as a file leave it nothing to add, and it takes no room. The tool asks the same
 * question to tell the model what the reader sees.
 */
export function showsTable(result: {
  rows: unknown[][];
  plan: boolean;
  exported: boolean;
  display?: "table" | "none";
}) {
  return result.display !== "none" && !result.plan && !result.exported && result.rows.length > 1;
}

/** A column name as a DuckDB identifier, whatever characters it holds. */
export function quoteIdentifier(name: string): string {
  return `"${name.replaceAll('"', '""')}"`;
}

/** The query without the semicolons and space a model may leave at its end. */
function statement(sql: string): string {
  return sql.replace(/[\s;]+$/u, "");
}

/** One page of `sql`'s rows, optionally in another order. */
export function pageSql(
  sql: string,
  page: { limit: number; offset: number; order?: SortOrder },
): string {
  const order = page.order
    ? ` ORDER BY ${quoteIdentifier(page.order.column)} ${page.order.descending ? "DESC" : "ASC"} NULLS LAST`
    : "";
  // The line break keeps a trailing line comment in the query from swallowing the bracket.
  return `SELECT * FROM (${statement(sql)}\n) AS result${order} LIMIT ${Math.trunc(page.limit)} OFFSET ${Math.trunc(page.offset)}`;
}

export { filterRows, sortRows, toTsv } from "../../../views/kit/rows";
