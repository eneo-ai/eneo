import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it } from "vitest";

import { m } from "$lib/paraglide/messages";

import BuilderToolsChip from "./BuilderToolsChip.svelte";
import type { AIBuilderSessionTool } from "./protocol";

afterEach(() => cleanup());

function tool(overrides: Partial<AIBuilderSessionTool>): AIBuilderSessionTool {
  return {
    ref: "tool_a",
    mcp_server_id: "11111111-1111-4111-8111-111111111111",
    mcp_server_name: "Records",
    mcp_server_security_level: null,
    tool_id: "22222222-2222-4222-8222-222222222221",
    tool_name: "lookup",
    tool_description: "Finds a record by its number.",
    refusal: null,
    ...overrides
  };
}

const LISTED = [
  tool({}),
  tool({ ref: "tool_b", tool_name: "history", tool_description: null }),
  tool({ ref: "tool_c", tool_name: "archive", refusal: "tool_switched_off_in_space" })
];

describe("BuilderToolsChip", () => {
  // Kills: the chip shown for a space whose tools no flow may use, or
  // counting a refused tool.
  it.each([
    { tools: [], label: null },
    { tools: [LISTED[2]!], label: null },
    { tools: LISTED, label: m.ai_builder_tools_chip({ servers: "Records", count: "2" }) }
  ])("names the usable tools of the space ($label)", ({ tools, label }) => {
    render(BuilderToolsChip, { tools });

    expect(screen.queryByRole("button")?.textContent?.trim() ?? null).toBe(label);
  });

  // Kills: the popover listing a refused tool or leaving out a description.
  it("lists each usable tool with its server and approved description", async () => {
    render(BuilderToolsChip, { tools: LISTED });

    await fireEvent.click(screen.getByRole("button"));

    const title = await screen.findByText(m.ai_builder_tools_popover_title());
    const popover = title.closest("[data-slot=popover-content]")!;
    expect([...popover.querySelectorAll("li")].map((item) => item.textContent?.trim())).toEqual([
      expect.stringMatching(/^lookup\s+Records\s+Finds a record by its number\.$/),
      expect.stringMatching(/^history\s+Records$/)
    ]);
  });
});
