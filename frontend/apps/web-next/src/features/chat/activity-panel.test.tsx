// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { EneoUIMessage } from "@/lib/chat/types";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { deriveActivity } from "./activity";
import { ActivityPanel, type ActivityTab } from "./activity-panel";
import { ActivityPill } from "./activity-pill";
import { sourceAnchorId } from "./activity-sources";
import type { TurnDurations } from "./activity-timings";

type Part = EneoUIMessage["parts"][number];

afterEach(cleanup);

const knowledge = [{ id: "group-1", name: "Upphandlingspolicy", kind: "collection" as const }];

const message: EneoUIMessage = {
  id: "answer-1",
  role: "assistant",
  metadata: {
    completionModel: { id: "m", name: "claude-haiku", nickname: "Claude Haiku 4.5" },
    tokens: { completion: 1842 }
  },
  parts: [
    {
      type: "source-document",
      sourceId: "doc-1",
      mediaType: "text/plain",
      title: "Upphandlingspolicy 2024.pdf",
      providerMetadata: { eneo: { group_id: "group-1" } }
    } as Part,
    {
      type: "source-document",
      sourceId: "doc-2",
      mediaType: "text/plain",
      title: "LOU 19 kap.",
      providerMetadata: { eneo: { metadata: { url: "https://riksdagen.se/lou" } } }
    } as Part,
    { type: "reasoning", text: "Jämför policyn mot LOU.", state: "done" },
    {
      type: "dynamic-tool",
      toolName: "lou_troskelvarden",
      toolCallId: "call-1",
      state: "output-available",
      input: { ar: 2026 },
      output: { status: "succeeded" },
      providerMetadata: { eneo: { server_name: "lou", approved: true } }
    } as Part,
    { type: "text", text: "Gränsen är 700 000 kr[1].", state: "done" }
  ]
};

const durations: TurnDurations = {
  totalMs: 14_600,
  stepMs: { knowledge: 2_100, "reasoning-0": 1_200, "tool-call-1": 600, answer: 5_900 },
  tokens: null,
  finishedAt: null
};

function Harness({
  initialSource = null,
  variant = "side"
}: {
  initialSource?: number | null;
  variant?: "side" | "sheet";
}) {
  const [open, setOpen] = useState(initialSource !== null);
  const [tab, setTab] = useState<ActivityTab>(initialSource !== null ? "sources" : "steps");
  const activity = deriveActivity(message, { knowledge });
  return (
    <>
      <ActivityPill
        activity={activity}
        durations={durations}
        expanded={open}
        onToggle={() => setOpen((value) => !value)}
      />
      {open && (
        <ActivityPanel
          variant={variant}
          messageId={message.id}
          activity={activity}
          durations={durations}
          sessionId={null}
          tab={tab}
          onTabChange={setTab}
          focusSource={initialSource}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

describe("ActivityPill", () => {
  it("summarises steps, time and sources and is a disclosure for the panel", () => {
    renderInApp(<Harness />);
    const pill = screen.getByRole("button", { name: /aktivitet: 4 steg · 14,6 s · 2 källor/i });
    expect(pill.getAttribute("aria-expanded")).toBe("false");
    expect(pill.hasAttribute("aria-controls")).toBe(false);

    fireEvent.click(pill);
    expect(pill.getAttribute("aria-expanded")).toBe("true");
    expect(pill.getAttribute("aria-controls")).toBe("chat-activity-panel");
    expect(document.getElementById("chat-activity-panel")).not.toBeNull();
  });

  it("names the running step while an answer streams", () => {
    const live = deriveActivity(
      {
        ...message,
        parts: [{ ...(message.parts[3] as Part), state: "input-available" } as Part]
      },
      { streaming: true }
    );
    renderInApp(
      <ActivityPill activity={live} durations={null} expanded={false} onToggle={vi.fn()} />
    );
    expect(
      screen.getByRole("button", { name: /aktivitet: lou_troskelvarden…|lou troskelvarden…/i })
    ).toBeTruthy();
  });
});

describe("ActivityPanel", () => {
  it("moves focus to the selected tab, lists steps with durations and closes on Escape", async () => {
    renderInApp(<Harness />);
    const pill = screen.getByRole("button", { name: /aktivitet:/i });
    fireEvent.click(pill);

    const panel = screen.getByRole("complementary", { name: "Aktivitet för svaret" });
    const stepsTab = within(panel).getByRole("tab", { name: "Steg" });
    await waitFor(() => expect(document.activeElement).toBe(stepsTab));
    expect(stepsTab.getAttribute("aria-selected")).toBe("true");

    const steps = within(panel).getByRole("tabpanel", { name: "Steg" });
    expect(within(steps).getByText("Sökte i kunskap")).toBeTruthy();
    expect(within(steps).getByText("Upphandlingspolicy")).toBeTruthy();
    expect(within(steps).getByText("2 träffar")).toBeTruthy();
    expect(within(steps).getByText("Resonerade")).toBeTruthy();
    expect(within(steps).getByText("Skrev svaret")).toBeTruthy();
    expect(within(steps).getByText("Claude Haiku 4.5 · 1 842 tokens")).toBeTruthy();
    expect(within(steps).getByText("Godkänt")).toBeTruthy();
    expect(within(steps).getByText("1,2 s")).toBeTruthy();
    expect(within(steps).getAllByText("Klar").length).toBeGreaterThan(0);
    expect(within(panel).getByText("Totalt 14,6 s")).toBeTruthy();

    fireEvent.keyDown(stepsTab, { key: "Escape" });
    expect(screen.queryByRole("complementary", { name: "Aktivitet för svaret" })).toBeNull();
    expect(pill.getAttribute("aria-expanded")).toBe("false");
  });

  it("keeps reasoning and tool call details behind disclosures", () => {
    renderInApp(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: /aktivitet:/i }));
    const reasoning = screen.getByRole("button", { name: "Resonemang" });
    expect(reasoning.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(reasoning);
    expect(reasoning.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("Jämför policyn mot LOU.")).toBeTruthy();
    // The tool call (Astryx ChatToolCalls): name, server and arguments; the
    // row expands to the full arguments.
    const call = screen.getByRole("button", { name: /lou_troskelvarden/ });
    expect(call.textContent).toContain("ar: 2026");
    expect(call.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(call);
    expect(call.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("Argument")).toBeTruthy();
  });

  it("switches to numbered sources with where they come from", () => {
    renderInApp(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: /aktivitet:/i }));
    fireEvent.click(screen.getByRole("tab", { name: /källor/i }));
    const sources = screen.getByRole("tabpanel", { name: "Källor" });
    const items = within(sources).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]!.textContent).toContain("Upphandlingspolicy 2024.pdf");
    expect(items[0]!.textContent).toContain("Upphandlingspolicy");
    const link = within(items[1]!).getByRole("link", { name: /LOU 19 kap\./ });
    expect(link.getAttribute("href")).toBe("https://riksdagen.se/lou");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(items[1]!.textContent).toContain("riksdagen.se");
  });

  it("focuses the source a citation opened", async () => {
    renderInApp(<Harness initialSource={1} />);
    const target = document.getElementById(sourceAnchorId(message.id, 2));
    await waitFor(() => expect(document.activeElement).toBe(target));
  });

  // Below 1024px (tablets, phones, 200–400% zoom) the panel is a modal sheet.
  it("focuses the cited source in the bottom sheet once it has opened", async () => {
    renderInApp(<Harness initialSource={1} variant="sheet" />);
    const sheet = await screen.findByRole("dialog", { name: "Aktivitet för svaret" });
    const target = document.getElementById(sourceAnchorId(message.id, 2));
    expect(sheet.contains(target)).toBe(true);
    await waitFor(() => expect(document.activeElement).toBe(target));
  });

  it("points the pill at the sheet it opens", async () => {
    renderInApp(<Harness variant="sheet" />);
    const pill = screen.getByRole("button", { name: /aktivitet:/i });
    fireEvent.click(pill);
    const sheet = await screen.findByRole("dialog", { name: "Aktivitet för svaret" });
    const controlled = document.getElementById(pill.getAttribute("aria-controls") ?? "");
    expect(controlled).not.toBeNull();
    expect(sheet.contains(controlled)).toBe(true);
    await expectNoAxeViolations(sheet);
  });

  it("has no axe violations with either tab open", async () => {
    renderInApp(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: /aktivitet:/i }));
    await expectNoAxeViolations(document.body);
    fireEvent.click(screen.getByRole("tab", { name: /källor/i }));
    await expectNoAxeViolations(document.body);
  });
});
