import { describe, expect, it } from "vitest";

import { readToolInputConfig, withToolInputConfig } from "./toolInputConfig";

describe("withToolInputConfig", () => {
  // Kills: the editor writes back keys of the stored tool object (a pin, a
  // pasted key), which the server refuses on an editable step; a stored
  // choice with such a key reads as the editor's own.
  it("writes the three editable keys and keeps the step's other input settings", () => {
    const tool = { mcp_server_id: "server-1", tool_id: "tool-1", arguments: { query: "x" } };

    expect(
      [tool, { ...tool, extra: 1 }].map((stored) => readToolInputConfig({ tool: stored }))
    ).toMatchObject([{ hasOtherKeys: false }, { hasOtherKeys: true }]);
    expect(
      withToolInputConfig(
        { runtime_input: false, tool: { ...tool, tool_name: "search", extra: 1 } },
        tool
      )
    ).toStrictEqual({ runtime_input: false, tool });
  });
});
