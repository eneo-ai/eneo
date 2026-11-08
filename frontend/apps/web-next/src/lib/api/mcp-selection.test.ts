import { expect, it } from "vitest";
import { mcpServersFromApi } from "./mcp-selection";

it("parses API server tools without trusting unknown payload shape", () => {
  expect(
    mcpServersFromApi([
      {
        id: "server-1",
        name: "Search",
        tools: [{ id: "tool-1", name: "query", is_enabled: true }, { id: "invalid" }]
      }
    ])
  ).toEqual([
    {
      id: "server-1",
      name: "Search",
      description: undefined,
      tools: [
        {
          id: "tool-1",
          name: "query",
          title: undefined,
          description: undefined,
          is_enabled: true,
          is_enabled_by_default: undefined,
          removed_from_remote: undefined
        }
      ]
    }
  ]);
});
