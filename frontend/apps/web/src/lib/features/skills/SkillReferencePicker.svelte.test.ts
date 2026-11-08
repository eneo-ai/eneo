import { page, userEvent } from "vitest/browser";
import { render } from "vitest-browser-svelte";
import { describe, expect, it, vi } from "vitest";
import type { ReferenceCandidate, ReferenceCatalog } from "@eneo/skill-instructions";
import { m } from "$lib/paraglide/messages";
import SkillReferencePicker from "./SkillReferencePicker.svelte";

const helper = {
  label: "Klartext",
  description: "Skriv begripligt.",
  revisionNumber: 4,
  target: {
    kind: "skill",
    skill_id: "11111111-1111-4111-8111-111111111111",
    revision_id: "22222222-2222-4222-8222-222222222222"
  }
} satisfies ReferenceCandidate;
function setup(overrides: Partial<ReferenceCatalog> = {}) {
  const catalog: ReferenceCatalog = {
    key: "space",
    skills: vi.fn().mockResolvedValue({ items: [helper], nextCursor: null }),
    servers: vi.fn().mockResolvedValue([]),
    tools: vi.fn().mockResolvedValue([]),
    preview: vi.fn().mockResolvedValue("Använd korta meningar."),
    ...overrides
  };
  const onSelect = vi.fn();
  render(SkillReferencePicker, {
    catalog,
    selection: { documentVersion: 0, from: 0, to: 0 },
    onSelect,
    onClose: vi.fn(),
    onRemove: vi.fn()
  });
  return { catalog, onSelect };
}

describe("reference selection", () => {
  it("exposes the active search result to assistive technology as arrow selection changes", async () => {
    setup();
    await page.getByRole("tab", { name: m.skills_reference_functions() }).click();
    const search = page.getByRole("combobox");
    await search.click();
    await expect.poll(() => search.element().getAttribute("aria-activedescendant")).toBeTruthy();
    const first = search.element().getAttribute("aria-activedescendant");
    await userEvent.keyboard("{ArrowDown}");
    await expect.poll(() => search.element().getAttribute("aria-activedescendant")).not.toBe(first);
    expect(search.element().getAttribute("aria-activedescendant")).toBe(
      document.querySelector('[role="option"][aria-selected="true"]')?.id
    );
  });

  it("keeps arrow navigation on the tabs and reaches search with Tab", async () => {
    setup();
    await page.getByRole("tab", { name: m.skills(), exact: true }).click();
    await userEvent.keyboard("{ArrowRight}");
    await expect
      .element(page.getByRole("tab", { name: m.skills_reference_functions() }))
      .toHaveFocus();
    await userEvent.keyboard("{ArrowRight}");
    await expect.element(page.getByRole("tab", { name: m.skills_reference_mcps() })).toHaveFocus();
    await userEvent.keyboard("{Tab}");
    await expect.element(page.getByRole("combobox")).toHaveFocus();
  });

  it("reviews an exact Skill version, recovers a failed preview, and keeps list and preview separate", async () => {
    const preview = vi
      .fn()
      .mockRejectedValueOnce(new Error("Try again"))
      .mockResolvedValue("Använd korta meningar.");
    const { onSelect } = setup({ preview });
    await expect.element(page.getByRole("combobox")).toHaveAttribute("aria-controls");
    await page.getByRole("option", { name: /Klartext/ }).click();
    await expect.element(page.getByRole("listbox")).not.toBeInTheDocument();
    await expect
      .element(page.getByRole("button", { name: m.skills_reference_insert(), exact: true }))
      .toBeDisabled();
    await page.getByRole("button", { name: m.retry() }).click();
    await expect.element(page.getByText("Använd korta meningar.")).toBeVisible();
    await page.getByRole("button", { name: m.skills_reference_insert(), exact: true }).click();
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining(helper));
    expect(
      preview.mock.calls.every(
        ([candidate]) => candidate.target.revision_id === helper.target.revision_id
      )
    ).toBe(true);
  });

  it("inserts a built-in function directly without a redundant review step", async () => {
    const { catalog, onSelect } = setup();
    await page.getByRole("tab", { name: m.skills_reference_functions() }).click();
    await page.getByRole("option", { name: m.web_search(), exact: true }).click();
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ target: { kind: "function", purpose: "web_search" } })
    );
    expect(catalog.preview).not.toHaveBeenCalled();
  });

  it("keeps the full description and long instructions available after choosing a truncated result", async () => {
    const long = {
      ...helper,
      label: "Kommunikationsguide ".repeat(10),
      description: "Beskrivning med många detaljer. ".repeat(30)
    };
    const instructions =
      "## Avsnitt\n\n- Gör texten tydlig.\n\n".repeat(200) + "Sista instruktionen.";
    setup({
      skills: vi.fn().mockResolvedValue({ items: [long], nextCursor: null }),
      preview: vi.fn().mockResolvedValue(instructions)
    });
    await page.getByRole("option", { name: /Kommunikationsguide/ }).click();
    await expect
      .poll(() => document.querySelector('[role="dialog"]')?.textContent)
      .toContain(instructions);
    await expect.element(page.getByText(long.description, { exact: true })).not.toBeVisible();
    await page.getByText(m.skills_description_label(), { exact: true }).click();
    await expect.element(page.getByText(long.description, { exact: true })).toBeVisible();
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain(long.description);
    await expect
      .element(page.getByRole("button", { name: m.skills_reference_insert(), exact: true }))
      .toBeEnabled();
  });

  it("allows a whole MCP or a specific approved tool and returns to the connections", async () => {
    const server: ReferenceCandidate = {
      label: "Time",
      description: "Datum",
      target: { kind: "mcp_server", server_id: "33333333-3333-4333-8333-333333333333" }
    };
    const tool: ReferenceCandidate = {
      label: "Today",
      description: "Tool details. ".repeat(60) + "Does not fetch external data.",
      target: {
        kind: "mcp_tool",
        server_id: "33333333-3333-4333-8333-333333333333",
        tool_name: "today"
      }
    };
    const { catalog, onSelect } = setup({
      servers: vi.fn().mockResolvedValue([server]),
      tools: vi.fn().mockResolvedValue([tool])
    });
    await page.getByRole("tab", { name: m.skills_reference_mcps() }).click();
    await page.getByRole("option", { name: /Time/ }).click();
    await expect
      .element(page.getByRole("button", { name: m.skills_reference_whole_mcp() }))
      .toBeEnabled();
    await page.getByRole("button", { name: m.skills_reference_tools() }).click();
    await expect.element(page.getByRole("combobox")).toHaveFocus();
    await page.getByRole("combobox").fill("Today");
    await page.getByRole("option", { name: /^Today/ }).click();
    await expect.element(page.getByText(tool.description!, { exact: true })).toBeVisible();
    expect(onSelect).not.toHaveBeenCalled();
    await page.getByRole("button", { name: m.skills_reference_back() }).click();
    await expect.element(page.getByRole("combobox")).toHaveValue("Today");
    await expect.element(page.getByRole("combobox")).toHaveFocus();
    await page.getByRole("option", { name: /^Today/ }).click();
    await page.getByRole("button", { name: m.skills_reference_insert(), exact: true }).click();
    expect(catalog.tools).toHaveBeenCalledWith(
      "33333333-3333-4333-8333-333333333333",
      expect.any(AbortSignal)
    );
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining(tool));
  });
});
