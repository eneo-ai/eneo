// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReferenceCandidate, ReferenceCatalog } from "@eneo/skill-instructions";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { SkillReferencePicker } from "./skill-reference-picker";
import { SkillInstructionEditor } from "./skill-instruction-editor";

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
function catalog(overrides: Partial<ReferenceCatalog> = {}): ReferenceCatalog {
  return {
    key: "space",
    skills: vi.fn().mockResolvedValue({ items: [helper], nextCursor: null }),
    servers: vi.fn().mockResolvedValue([]),
    tools: vi.fn().mockResolvedValue([]),
    preview: vi.fn().mockResolvedValue("Använd korta meningar."),
    ...overrides
  };
}
afterEach(cleanup);

describe("instruction references", () => {
  it("handles Escape inside an inline picker before it reaches the enclosing form", async () => {
    const onClose = vi.fn();
    const outerKeyDown = vi.fn();
    renderInApp(
      <div onKeyDown={outerKeyDown}>
        <SkillReferencePicker
          inline
          catalog={catalog()}
          selection={{ documentVersion: 0, from: 0, to: 0 }}
          onSelect={vi.fn()}
          onClose={onClose}
          onRemove={vi.fn()}
        />
      </div>
    );
    const input = await screen.findByRole("textbox", { name: "Sök referens" });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
    expect(outerKeyDown).not.toHaveBeenCalled();
  });
  it("reviews the pinned Skill, recovers a failed preview, and supports keyboard selection", async () => {
    const preview = vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue("Använd korta meningar.");
    const onSelect = vi.fn();
    renderInApp(
      <SkillReferencePicker
        catalog={catalog({ preview })}
        selection={{ documentVersion: 0, from: 0, to: 0 }}
        onSelect={onSelect}
        onClose={vi.fn()}
        onRemove={vi.fn()}
      />
    );
    const option = await screen.findByRole("button", { name: /Klartext/ });
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Sök referens" }), { key: "ArrowDown" });
    expect(document.activeElement).toBe(option);
    await expectNoAxeViolations();
    fireEvent.click(option);
    const insert = screen.getByRole("button", { name: "Infoga referens" });
    await screen.findByRole("button", { name: "Försök igen" });
    expect(insert.hasAttribute("disabled")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    await screen.findByText("Använd korta meningar.");
    expect(screen.queryByRole("textbox", { name: "Sök referens" })).toBeNull();
    expect(screen.getByText(helper.description)).toBeTruthy();
    await expectNoAxeViolations();
    fireEvent.click(insert);
    expect(onSelect).toHaveBeenCalledWith(helper);
    expect(
      preview.mock.calls.every(
        ([candidate]) => candidate.target.revision_id === helper.target.revision_id
      )
    ).toBe(true);
  });

  it("inserts functions directly and supports a whole MCP or its exact tool", async () => {
    const server: ReferenceCandidate = {
      label: "Time",
      description: "Datum",
      target: { kind: "mcp_server", server_id: "33333333-3333-4333-8333-333333333333" }
    };
    const tool: ReferenceCandidate = {
      label: "Today",
      description: "Full tool description. ".repeat(30) + "No external data is fetched.",
      target: {
        kind: "mcp_tool",
        server_id: "33333333-3333-4333-8333-333333333333",
        tool_name: "today"
      }
    };
    const onSelect = vi.fn();
    const source = catalog({
      servers: vi.fn().mockResolvedValue([server]),
      tools: vi.fn().mockResolvedValue([tool])
    });
    renderInApp(
      <SkillReferencePicker
        catalog={source}
        selection={{ documentVersion: 0, from: 0, to: 0 }}
        onSelect={onSelect}
        onClose={vi.fn()}
        onRemove={vi.fn()}
      />
    );
    fireEvent.click(screen.getByRole("radio", { name: "Funktioner" }));
    fireEvent.click(await screen.findByRole("button", { name: "Webbsökning" }));
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ target: { kind: "function", purpose: "web_search" } })
    );
    fireEvent.click(screen.getByRole("radio", { name: "MCP" }));
    fireEvent.click(await screen.findByRole("button", { name: /Time/ }));
    fireEvent.click(screen.getByRole("button", { name: "Använd hela anslutningen" }));
    expect(onSelect).toHaveBeenCalledWith(server);
    fireEvent.click(screen.getByRole("button", { name: "Välj specifikt verktyg" }));
    fireEvent.click(await screen.findByRole("button", { name: /^Today/ }));
    expect(onSelect).not.toHaveBeenCalledWith(tool);
    expect(screen.getByText(tool.description!)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Välj specifikt verktyg" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Infoga referens" }));
    expect(onSelect).toHaveBeenCalledWith(tool);
    expect(source.preview).not.toHaveBeenCalled();
  });

  it("keeps complete long descriptions and instructions available in the preview", async () => {
    const long = {
      ...helper,
      label: "Kommunikationsguide ".repeat(10),
      description: "Beskrivning med många detaljer. ".repeat(30)
    };
    const instructions =
      "## Avsnitt\n\n- Gör texten tydlig.\n\n".repeat(200) + "Sista instruktionen.";
    renderInApp(
      <SkillReferencePicker
        catalog={catalog({
          skills: vi.fn().mockResolvedValue({ items: [long], nextCursor: null }),
          preview: vi.fn().mockResolvedValue(instructions)
        })}
        selection={{ documentVersion: 0, from: 0, to: 0 }}
        onSelect={vi.fn()}
        onClose={vi.fn()}
        onRemove={vi.fn()}
      />
    );
    fireEvent.click(await screen.findByRole("button", { name: /Kommunikationsguide/ }));
    await waitFor(() => expect(screen.getByRole("dialog").textContent).toContain(instructions));
    const descriptionToggle = screen.getByText("Beskrivning", { selector: "summary" });
    expect(descriptionToggle.parentElement?.hasAttribute("open")).toBe(false);
    fireEvent.click(descriptionToggle);
    expect(descriptionToggle.parentElement?.hasAttribute("open")).toBe(true);
    expect(screen.getByRole("dialog").textContent).toContain(long.description);
    expect(
      within(screen.getByRole("dialog"))
        .getByRole("button", { name: "Infoga referens" })
        .hasAttribute("disabled")
    ).toBe(false);
  });

  it("exposes a named, described editor with accessible reference tokens", async () => {
    renderInApp(
      <SkillInstructionEditor
        id="instructions"
        value="Använd [Sök](eneo-function:web_search)."
        onChange={vi.fn()}
        disabled={false}
        invalid={false}
        catalog={catalog()}
      />
    );
    await screen.findByRole("textbox", { name: "Instruktioner" });
    await expectNoAxeViolations();
  });
});
