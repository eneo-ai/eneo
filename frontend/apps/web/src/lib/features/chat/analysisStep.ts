/** Cheap, conservative activity labels for the bundled spreadsheet tools.
 * This recognises simple outer-query structure, not SQL meaning. Complex
 * grouping expressions fall back to a general operation label.
 */
export type AnalysisStep = {
  kind: "inspect" | "check" | "sum" | "count" | "query";
  groups: string[];
};
type SqlToken = { value: string; quoted: boolean };
function outerTokens(sql: string): SqlToken[] {
  const tokens =
    sql.match(
      /--[^\n]*|\/\*[\s\S]*?\*\/|'(?:''|[^'])*'|"(?:""|[^"])*"|[\p{L}_][\p{L}\p{N}_$]*|\d+|[^\s]/gu
    ) ?? [];
  let depth = 0;
  const outer: SqlToken[] = [];
  for (const value of tokens) {
    if (value.startsWith("--") || value.startsWith("/*") || value.startsWith("'")) continue;
    if (value === ")") {
      depth = Math.max(0, depth - 1);
      continue;
    }
    if (depth === 0)
      outer.push({
        value: value.startsWith('"') ? value.slice(1, -1).replaceAll('""', '"') : value,
        quoted: value.startsWith('"')
      });
    if (value === "(") depth++;
  }
  return outer;
}
const keyword = (token: SqlToken | undefined, value: string) =>
  !token?.quoted && token?.value.toUpperCase() === value;
function grouping(tokens: SqlToken[]): string[] {
  const start = tokens.findIndex(
    (token, i) => keyword(token, "GROUP") && keyword(tokens[i + 1], "BY")
  );
  if (start < 0) return [];
  const groups: string[] = [];
  let field: SqlToken[] = [];
  const save = () => {
    // A column or table-qualified column only. Never guess at expressions or ordinals.
    const identifier = (token: SqlToken) =>
      token.quoted ||
      (!/^(ALL|ROLLUP|CUBE|GROUPING)$/i.test(token.value) &&
        /^[\p{L}_][\p{L}\p{N}_$]*$/u.test(token.value));
    if (
      !(field.length === 1 && identifier(field[0])) &&
      !(
        field.length === 3 &&
        identifier(field[0]) &&
        field[1].value === "." &&
        identifier(field[2])
      )
    )
      return false;
    groups.push(field.at(-1)!.value.replaceAll("_", " "));
    field = [];
    return true;
  };
  for (const token of tokens.slice(start + 2)) {
    if (
      [
        "ORDER",
        "HAVING",
        "LIMIT",
        "OFFSET",
        "FETCH",
        "UNION",
        "EXCEPT",
        "INTERSECT",
        "WINDOW"
      ].some((word) => keyword(token, word)) ||
      token.value === ";"
    )
      break;
    if (token.value === ",") {
      if (!save()) return [];
    } else field.push(token);
  }
  if (!save()) return [];
  return groups.length <= 3 ? [...new Set(groups)] : [];
}
export function analysisStep(
  call: { is_bundled?: boolean | null; purpose?: string | null; tool_name: string },
  args?: Record<string, unknown>
): AnalysisStep | null {
  if (!call.is_bundled || call.purpose !== "file_analysis") return null;
  if (call.tool_name === "inspect_table") return { kind: "inspect", groups: [] };
  if (call.tool_name === "assert_table") return { kind: "check", groups: [] };
  if (call.tool_name !== "query_table") return null;
  const tokens = outerTokens(typeof args?.sql === "string" ? args.sql : "");
  const hasFunction = (name: string) =>
    tokens.some((token, i) => keyword(token, name) && tokens[i + 1]?.value === "(");
  const kind = ["SUM", "AVG", "MIN", "MAX"].some(hasFunction)
    ? "sum"
    : hasFunction("COUNT")
      ? "count"
      : "query";
  return { kind, groups: kind === "query" ? [] : grouping(tokens) };
}
