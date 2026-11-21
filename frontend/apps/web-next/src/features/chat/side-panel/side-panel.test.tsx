// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
import type { EneoUIMessage } from "@/lib/chat/types";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { observedElements, reportResize, setViewport } from "@/test/setup-dom";
import { SidePanel, type SidePanelLayout } from "./side-panel";
import { SidePanelStore } from "./side-panel-store";

afterEach(cleanup);

const PANEL = "Aktivitet för svaret";

/**
 * A conversation with an answer's "2 steg" pill and a composer, and the
 * answer's activity as the panel's occupant: open from the start (as from
 * the panel's switcher, with no opener to go back to) unless `closed`.
 * Closing gives the focus back to the pill that opened it, as the chat view
 * does.
 */
function Harness({ layout, closed = false }: { layout?: SidePanelLayout; closed?: boolean }) {
  const [panel] = useState(() => new SidePanelStore(() => Promise.reject(new Error("unused"))));
  const [open, setOpen] = useState(!closed);
  const opener = useRef<HTMLElement | null>(null);
  return (
    <SidePanel
      panel={panel}
      messages={[]}
      contents={{ views: [], documents: [], uploads: [] }}
      versionsOf={() => []}
      exportOf={() => null}
      saverOf={() => null}
      latestActivity={null}
      layout={layout}
      activity={
        open
          ? {
              detail: "2 steg",
              onClose: () => {
                setOpen(false);
                const pill = opener.current;
                opener.current = null;
                if (pill) requestAnimationFrame(() => pill.focus());
              },
              body: <button type="button">Steg 1</button>
            }
          : null
      }
    >
      <button
        type="button"
        onClick={(event) => {
          opener.current = event.currentTarget;
          setOpen(true);
        }}
      >
        Visa stegen
      </button>
      <textarea aria-label="Fråga" />
    </SidePanel>
  );
}

/** Lays out the region that holds the conversation and the panel at `width` px. */
const layOut = (width: number) =>
  act(() => {
    const region = observedElements().find((element) =>
      element.contains(screen.getByLabelText("Fråga"))
    );
    if (!region) throw new Error("The conversation's region is not measured");
    reportResize(region, { width, height: 800 });
  });

const beside = () => screen.queryByRole("complementary", { name: PANEL });
const sheet = () => screen.queryByRole("dialog", { name: PANEL });
const inColumn = () => screen.queryByRole("region", { name: PANEL });
/** What holds the conversation and its composer, beside or under the panel. */
const conversation = () => screen.getByLabelText("Fråga").parentElement!;
const COLUMN: SidePanelLayout = { inColumn: true };

describe("SidePanel by the width it has (decision 14)", () => {
  it("is not beside the conversation before its room is known", () => {
    renderInApp(<Harness />);
    expect(beside()).toBeNull();
  });

  it("sits beside the conversation when that keeps 480 px", () => {
    renderInApp(<Harness />);
    layOut(1008);
    expect(beside()?.style.width).toBe("520px");
    expect(sheet()).toBeNull();
  });

  it("narrows to leave the conversation 480 px (an iPad sideways: 908 px)", () => {
    renderInApp(<Harness />);
    layOut(908);
    // 908 − the 4 px handle − 480.
    expect(beside()?.style.width).toBe("424px");
  });

  it("covers the conversation as a sheet when it cannot (an iPad upright: 820 px)", () => {
    renderInApp(<Harness />);
    layOut(820);
    expect(sheet()).not.toBeNull();
    expect(beside()).toBeNull();
    // The chat page's own conversation asks for no column.
    expect(inColumn()).toBeNull();
  });
});

describe("SidePanel in the conversation's column (a chat that is a column of a wider page)", () => {
  it("covers the conversation and its composer in the column, not as a sheet", () => {
    renderInApp(<Harness layout={COLUMN} />);
    layOut(360);

    const panel = inColumn();
    expect(panel).not.toBeNull();
    expect(sheet()).toBeNull();
    expect(beside()).toBeNull();
    // Laid over the conversation inside the column, not over the window.
    expect(panel!.className).toContain("absolute");
    expect(panel!.className).not.toContain("fixed");
    expect(panel!.parentElement?.contains(conversation())).toBe(true);
    expect(screen.getByRole("button", { name: "Stäng panelen" })).toBeTruthy();
  });

  it("still sits beside the conversation where the column has room", () => {
    renderInApp(<Harness layout={COLUMN} />);
    layOut(1008);
    expect(beside()).not.toBeNull();
    expect(inColumn()).toBeNull();
    expect(conversation().hasAttribute("inert")).toBe(false);
  });

  it("is the sheet on a phone, whatever the layout asks", () => {
    setViewport("phone");
    renderInApp(<Harness layout={COLUMN} />);
    layOut(390);
    expect(sheet()).not.toBeNull();
    expect(inColumn()).toBeNull();
  });

  it("keeps the conversation mounted and out of reach underneath, as it was", () => {
    renderInApp(<Harness layout={COLUMN} closed />);
    layOut(360);
    const composer = screen.getByLabelText<HTMLTextAreaElement>("Fråga");
    fireEvent.change(composer, { target: { value: "Ett utkast" } });
    expect(conversation().hasAttribute("inert")).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Visa stegen" }));
    expect(inColumn()).not.toBeNull();
    expect(conversation().hasAttribute("inert")).toBe(true);
    expect(screen.getByLabelText("Fråga")).toBe(composer);

    fireEvent.keyDown(screen.getByRole("button", { name: "Steg 1" }), { key: "Escape" });
    expect(inColumn()).toBeNull();
    expect(conversation().hasAttribute("inert")).toBe(false);
    expect(screen.getByLabelText("Fråga")).toBe(composer);
    expect(composer.value).toBe("Ett utkast");
  });

  it("takes the focus from what opened it, and Escape gives it back", async () => {
    renderInApp(<Harness layout={COLUMN} closed />);
    layOut(360);
    const pill = screen.getByRole("button", { name: "Visa stegen" });
    act(() => pill.focus());

    fireEvent.click(pill);
    expect(inColumn()?.contains(document.activeElement)).toBe(true);

    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(inColumn()).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(pill));
  });

  it("gives the focus to the composer when nothing in the conversation opened it", async () => {
    renderInApp(<Harness layout={COLUMN} />);
    layOut(360);
    act(() => screen.getByRole("button", { name: "Steg 1" }).focus());

    fireEvent.click(screen.getByRole("button", { name: "Stäng panelen" }));
    expect(inColumn()).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText("Fråga")));
  });

  it("takes the focus from the conversation it comes to cover", () => {
    renderInApp(<Harness layout={COLUMN} />);
    layOut(1008);
    const composer = screen.getByLabelText("Fråga");
    act(() => composer.focus());

    layOut(820);
    expect(inColumn()?.contains(document.activeElement)).toBe(true);
  });

  it("has no axe violations", async () => {
    const { container } = renderInApp(<Harness layout={COLUMN} />);
    layOut(360);
    expect(inColumn()).not.toBeNull();
    await expectNoAxeViolations(container);
  });
});

describe("SidePanel focus across presentations (F7)", () => {
  it("takes the focus in the panel along when the panel changes presentation", () => {
    renderInApp(<Harness />);
    layOut(1008);
    act(() => screen.getByRole("button", { name: "Steg 1" }).focus());

    layOut(820);
    expect(sheet()?.contains(document.activeElement)).toBe(true);

    layOut(1008);
    expect(beside()?.contains(document.activeElement)).toBe(true);
  });

  it("leaves the focus in the conversation while the panel stays beside it", () => {
    renderInApp(<Harness />);
    layOut(1008);
    const composer = screen.getByLabelText("Fråga");
    act(() => composer.focus());

    layOut(908);
    expect(document.activeElement).toBe(composer);
  });

  it("follows dialog focus rules as a sheet", () => {
    renderInApp(<Harness />);
    layOut(1008);
    act(() => screen.getByLabelText("Fråga").focus());

    layOut(820);
    expect(sheet()?.contains(document.activeElement)).toBe(true);
  });
});

describe("SidePanel as a cover (an interactive view that cannot sit beside)", () => {
  /** An answer whose tool call has a view. */
  const withView: EneoUIMessage[] = [
    {
      id: "a1",
      role: "assistant",
      parts: [
        {
          type: "dynamic-tool",
          toolName: "query_table",
          toolCallId: "c1",
          state: "output-available",
          input: {},
          output: { status: "succeeded" },
          callProviderMetadata: {
            eneo: {
              server_name: "runtime",
              is_bundled: true,
              app_view: { view_id: "view-1", mcp_server_id: "server-1", ui: {} },
              approved: null
            }
          }
        }
      ] as unknown as EneoUIMessage["parts"]
    }
  ];

  function ViewHarness({ layout }: { layout?: SidePanelLayout }) {
    const [panel] = useState(() => {
      const store = new SidePanelStore(() => Promise.reject(new Error("unused")));
      store.openView("c1");
      return store;
    });
    return (
      <SidePanel
        panel={panel}
        messages={withView}
        contents={{ views: [], documents: [], uploads: [] }}
        versionsOf={() => []}
        exportOf={() => null}
        saverOf={() => null}
        latestActivity={null}
        layout={layout}
        activity={null}
      >
        <textarea aria-label="Fråga" />
      </SidePanel>
    );
  }

  it("covers the conversation in its column instead, for a chat that is a column", () => {
    renderInApp(<ViewHarness layout={COLUMN} />);
    layOut(1008);
    const composer = screen.getByLabelText("Fråga");
    act(() => composer.focus());

    layOut(360);
    const panel = screen.getByRole("region", { name: "Interaktiv verktygsvy" });
    expect(panel.className).toContain("absolute");
    expect(panel.className).not.toContain("fixed");
    expect(screen.queryByRole("complementary")).toBeNull();
    expect(panel.contains(document.activeElement)).toBe(true);
    // The view's frame lives in its message there and is laid out over the panel.
    expect(conversation().hasAttribute("inert")).toBe(false);
  });

  it("takes the focus from the conversation it now covers (WCAG 2.4.11)", () => {
    renderInApp(<ViewHarness />);
    layOut(1008);
    const composer = screen.getByLabelText("Fråga");
    act(() => composer.focus());

    layOut(800);
    const cover = screen.getByRole("complementary");
    expect(cover.className).toContain("fixed");
    // It escapes the shell frame, which pads for the notch and the home indicator.
    for (const side of ["top", "right", "bottom", "left"]) {
      expect(cover.className).toContain(`env(safe-area-inset-${side},0px)`);
    }
    expect(cover.contains(document.activeElement)).toBe(true);
  });
});
