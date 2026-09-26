// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ToolApprovalData } from "@/lib/chat/types";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { ToolApprovalCard } from "./message-parts";

const api = vi.hoisted(() => ({
  POST: vi.fn(async () => ({ data: {}, response: new Response() }))
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

afterEach(() => {
  cleanup();
  api.POST.mockClear();
});

const lookup = { server_name: "lou", tool_name: "troskelvarden", tool_call_id: "call-1" };
const register = { server_name: "diarium", tool_name: "sok_arende", tool_call_id: "call-2" };

function renderCard(data: ToolApprovalData) {
  return renderInApp(<ToolApprovalCard data={data} />);
}

/** The approve-tools request bodies sent so far. */
function decisionsSent() {
  return api.POST.mock.calls.map((call) => (call as unknown[])[1]);
}

describe("ToolApprovalCard", () => {
  it("names each decision after its tool and records the decision", async () => {
    renderCard({ approval_id: "approval-1", status: "pending", tools: [lookup] });
    const card = screen.getByRole("region", { name: "Väntar på godkännande" });

    // The visible text stays short; the accessible name says which tool.
    const approve = within(card).getByRole("button", { name: "Godkänn lou/troskelvarden" });
    expect(approve.textContent).toBe("Godkänn");
    expect(within(card).getByRole("button", { name: "Avvisa lou/troskelvarden" })).toBeTruthy();
    // One tool: no "all" actions.
    expect(within(card).queryByRole("button", { name: /alla/ })).toBeNull();

    fireEvent.click(approve);
    await waitFor(() => expect(within(card).getByText("Godkänt")).toBeTruthy());
    expect(decisionsSent()).toEqual([
      {
        params: { query: { approval_id: "approval-1" } },
        body: [{ tool_call_id: "call-1", approved: true }]
      }
    ]);
    expect(screen.getByRole("region", { name: "Verktygsgodkännande" })).toBeTruthy();
    expect(within(card).queryByRole("button")).toBeNull();
  });

  it("tells several pending tools apart and denies them all at once", async () => {
    renderCard({ approval_id: "approval-2", status: "pending", tools: [lookup, register] });
    expect(screen.getByRole("button", { name: "Godkänn lou/troskelvarden" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Godkänn diarium/sok_arende" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Godkänn alla (2)" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Avvisa alla" }));
    await waitFor(() => expect(screen.getAllByText("Nekat")).toHaveLength(2));
    expect(decisionsSent()).toEqual([
      {
        params: { query: { approval_id: "approval-2" } },
        body: [
          { tool_call_id: "call-1", approved: false },
          { tool_call_id: "call-2", approved: false }
        ]
      }
    ]);
  });

  it("denies one tool and keeps asking about the other", async () => {
    renderCard({ approval_id: "approval-3", status: "pending", tools: [lookup, register] });
    fireEvent.click(screen.getByRole("button", { name: "Avvisa diarium/sok_arende" }));
    await waitFor(() => expect(screen.getByText("Nekat")).toBeTruthy());
    expect(screen.getByRole("button", { name: "Godkänn lou/troskelvarden" })).toBeTruthy();
    // A single tool is left, so the "all" actions go away.
    expect(screen.queryByRole("button", { name: "Avvisa alla" })).toBeNull();
  });

  it("keeps focus on a busy Godkänn and sends one decision", async () => {
    api.POST.mockReturnValueOnce(new Promise(() => {}));
    renderCard({ approval_id: "approval-1", status: "pending", tools: [lookup, register] });
    const approve = screen.getByRole("button", { name: "Godkänn lou/troskelvarden" });
    approve.focus();

    fireEvent.click(approve);

    await waitFor(() => expect(approve.getAttribute("aria-busy")).toBe("true"));
    expect(approve.hasAttribute("disabled")).toBe(false);
    expect(document.activeElement).toBe(approve);
    fireEvent.click(approve);
    fireEvent.click(screen.getByRole("button", { name: "Avvisa alla" }));
    expect(api.POST).toHaveBeenCalledTimes(1);
  });

  it("shows tools that timed out as denied, without actions", () => {
    renderCard({ approval_id: "approval-4", status: "timeout_denied", tools: [lookup, register] });
    const card = screen.getByRole("region", { name: "Verktygsgodkännande" });
    expect(within(card).getAllByText("Avvisad, tiden gick ut")).toHaveLength(2);
    expect(within(card).queryByRole("button")).toBeNull();
  });

  it("has no axe violations", async () => {
    const { container } = renderCard({
      approval_id: "approval-5",
      status: "pending",
      tools: [lookup, register]
    });
    await expectNoAxeViolations(container);
  });
});
