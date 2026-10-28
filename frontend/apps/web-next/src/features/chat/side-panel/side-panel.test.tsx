// @vitest-environment jsdom
import { act, cleanup, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
import type { EneoUIMessage } from "@/lib/chat/types";
import { renderInApp } from "@/test/render";
import { observedElements, reportResize } from "@/test/setup-dom";
import { SidePanel } from "./side-panel";
import { SidePanelStore } from "./side-panel-store";

afterEach(cleanup);

const PANEL = "Aktivitet för svaret";

/** A conversation with a composer, and an answer's activity as the panel's occupant. */
function Harness() {
  const [panel] = useState(() => new SidePanelStore(() => Promise.reject(new Error("unused"))));
  const [open, setOpen] = useState(true);
  return (
    <SidePanel
      panel={panel}
      messages={[]}
      contents={{ views: [], documents: [], uploads: [] }}
      versionsOf={() => []}
      exportOf={() => null}
      saverOf={() => null}
      latestActivity={null}
      activity={
        open
          ? {
              detail: "2 steg",
              onClose: () => setOpen(false),
              body: <button type="button">Steg 1</button>
            }
          : null
      }
    >
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

  function ViewHarness() {
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
        activity={null}
      >
        <textarea aria-label="Fråga" />
      </SidePanel>
    );
  }

  it("takes the focus from the conversation it now covers (WCAG 2.4.11)", () => {
    renderInApp(<ViewHarness />);
    layOut(1008);
    const composer = screen.getByLabelText("Fråga");
    act(() => composer.focus());

    layOut(800);
    const cover = screen.getByRole("complementary");
    expect(cover.className).toContain("fixed");
    expect(cover.contains(document.activeElement)).toBe(true);
  });
});
