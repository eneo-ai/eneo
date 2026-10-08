import { describe, expect, test, mock } from "bun:test";
import { z } from "zod";
import { createHandler } from "../../src/server";
import { chartConfigSchema } from "../../src/tools/charts/config";
import { chartTools } from "../../src/tools/charts/tool";
import { MAX_SERIES } from "../../src/tools/charts/spec";

const run = mock(async () => {
  throw new Error("Invalid input must never render");
});
const download = mock(async () => {
  throw new Error("Invalid input must never download");
});
const tool = chartTools(chartConfigSchema.parse({}), run, {
  allowedFileOrigins: [],
  maxBytes: 1000,
  timeoutMs: 1000,
  download,
})[0]!;
const handler = createHandler({
  token: "chart-contract-test",
  maxConcurrency: 1,
  endpoints: [{ slug: "charts", tools: [tool], toolTimeoutMs: 1000 }],
});
async function rpc(method: string, params: unknown) {
  const response = await handler(
    new Request("http://runtime/mcp/charts", {
      method: "POST",
      headers: {
        authorization: "Bearer chart-contract-test",
        "content-type": "application/json",
        accept: "application/json, text/event-stream",
      },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
    }),
  );
  return (await response.json()) as {
    result: {
      tools: Array<{
        description: string;
        inputSchema: { properties: Record<string, any> };
      }>;
      isError: boolean;
      content: Array<{ text: string }>;
    };
  };
}
const columns = Array.from(
  { length: MAX_SERIES + 2 },
  (_, index) => `Department ${index + 1}`,
);
const source = {
  url: "https://files.example/report.csv",
  filename: "report.csv",
  label_column: "Month",
  value_columns: columns,
};

describe("chart input contract", () => {
  test("advertises the series limit and recovery for both input forms in the MCP catalog", async () => {
    const { result } = await rpc("tools/list", {});
    const chart = result.tools[0]!;
    expect(chart.description).toContain("BOTH inputs");
    expect(chart.description).toContain(
      "two charts with five value_columns each",
    );
    const properties = chart.inputSchema.properties;
    for (const field of [
      properties.series,
      properties.source.properties.value_columns,
    ]) {
      expect(field.maxItems).toBe(MAX_SERIES);
      expect(field.description).toContain("separate create_chart calls");
      expect(field.description).toContain("do not silently drop columns");
    }
  });

  for (const [name, args] of [
    ["source columns", { type: "line", source }],
    [
      "inline series",
      {
        type: "line",
        labels: ["January"],
        series: columns.map((name) => ({ name, values: [1] })),
      },
    ],
  ] as const) {
    test(`rejects oversized ${name} with actionable guidance before doing work`, async () => {
      const { result } = await rpc("tools/call", {
        name: "create_chart",
        arguments: args,
      });
      expect(result.isError).toBe(true);
      const text = result.content.map((block) => block.text).join("\n");
      expect(text).toContain(`at most ${MAX_SERIES}`);
      expect(text).toContain("separate create_chart calls");
      expect(text).toContain("not a file-reading failure");
      expect(run).not.toHaveBeenCalled();
      expect(download).not.toHaveBeenCalled();
    });
  }

  test("accepts the exact boundary and both halves of a ten-column comparison", () => {
    const input = z.object(tool.inputSchema);
    expect(
      input.safeParse({
        type: "line",
        source: { ...source, value_columns: columns.slice(0, MAX_SERIES) },
      }).success,
    ).toBe(true);
    const groups = [columns.slice(0, 5), columns.slice(5)];
    for (const value_columns of groups) {
      expect(
        input.safeParse({ type: "line", source: { ...source, value_columns } })
          .success,
      ).toBe(true);
    }
    expect(groups.flat()).toEqual(columns);
  });
});
