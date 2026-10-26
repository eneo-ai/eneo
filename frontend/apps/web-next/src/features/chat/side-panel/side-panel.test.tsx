// @vitest-environment jsdom
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { useState, useSyncExternalStore } from "react";
import { describe, expect, it, vi } from "vitest";
import type { PreviewFile } from "@/features/workspace/preview/preview-kind";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { reportResize, setViewport } from "@/test/setup-dom";
import type { PanelContents } from "./panel-contents";
import { BESIDE_MIN_WIDTH, SidePanel, sidePanelMode } from "./side-panel";
import { SidePanelStore } from "./side-panel-store";

vi.mock("@/features/workspace/preview/load-preview", () => ({
  loadPreview: vi.fn(() =>
    Promise.resolve({ kind: "markdown", text: "# Rapport\n\nInledning.", truncated: false })
  ),
  PreviewTooLargeError: class extends Error {}
}));

const EMPTY_CONTENTS: PanelContents = { views: [], documents: [], uploads: [] };

const upload: PreviewFile = {
  id: "upload-1",
  name: "underlag.md",
  mimetype: "text/markdown",
  size: 120
};

/**
 * The panel around a conversation, with an answer's activity as its occupant
 * (opened with the button in the conversation), and a store a test can drive.
 */
function Harness({
  store,
  contents = EMPTY_CONTENTS,
  initiallyOpen = false
}: {
  store: SidePanelStore;
  contents?: PanelContents;
  initiallyOpen?: boolean;
}) {
  const [open, setOpen] = useState(initiallyOpen);
  // As the conversation does: every change of the store re-renders the panel.
  useSyncExternalStore(store.subscribe, store.getVersion, store.getVersion);
  return (
    <SidePanel
      panel={store}
      messages={[]}
      contents={contents}
      versionsOf={() => []}
      exportOf={() => null}
      saverOf={() => null}
      latestActivity={null}
      activity={
        open
          ? {
              detail: "3 steg",
              onClose: () => setOpen(false),
              body: (
                <div className="p-4">
                  <button type="button">Steg</button>
                </div>
              )
            }
          : null
      }
    >
      <div data-testid="conversation">
        <button type="button" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
          Aktivitet
        </button>
      </div>
    </SidePanel>
  );
}

function store() {
  return new SidePanelStore(() => Promise.resolve("/file"));
}

/** The row the conversation and the panel share: what the panel measures. */
function row(): HTMLElement {
  return screen.getByTestId("conversation").parentElement!.parentElement!;
}

function panelRegion(name = "Aktivitet för svaret") {
  return screen.getByRole("complementary", { name });
}

describe("sidePanelMode", () => {
  it("is a sheet below 1024px whatever the region", () => {
    expect(sidePanelMode(false, null)).toBe("sheet");
    expect(sidePanelMode(false, 1400)).toBe("sheet");
  });

  it("is beside in a wide region, and over in a narrow one", () => {
    expect(sidePanelMode(true, 1200)).toBe("beside");
    expect(sidePanelMode(true, BESIDE_MIN_WIDTH)).toBe("beside");
    expect(sidePanelMode(true, BESIDE_MIN_WIDTH - 1)).toBe("over");
    expect(sidePanelMode(true, 420)).toBe("over");
  });

  it("takes an unmeasured region as wide, so the panel never starts over and jumps beside", () => {
    expect(sidePanelMode(true, null)).toBe("beside");
  });
});

describe("SidePanel layout", () => {
  it("sits beside the conversation with a handle when the region is wide", () => {
    const panel = store();
    renderInApp(<Harness store={panel} />);
    act(() => reportResize(row(), { width: 1200 }));
    fireEvent.click(screen.getByRole("button", { name: "Aktivitet" }));

    const aside = panelRegion();
    expect(aside.className).toContain("relative");
    expect(aside.className).not.toContain("absolute");
    expect(aside.style.width).not.toBe("");
    expect(
      screen.getByRole("separator", { name: "Ändra bredd på förhandsgranskningen" })
    ).toBeTruthy();
    expect(panel.besideConversation).toBe(true);
  });

  it("covers the conversation in a narrow region of a wide window", () => {
    const panel = store();
    renderInApp(<Harness store={panel} />);
    act(() => reportResize(row(), { width: 420 }));
    fireEvent.click(screen.getByRole("button", { name: "Aktivitet" }));

    const aside = panelRegion();
    expect(aside.className).toContain("absolute");
    expect(aside.className).toContain("inset-0");
    expect(aside.style.width).toBe("");
    expect(screen.queryByRole("separator")).toBeNull();
    // The conversation stays mounted under the panel.
    expect(row().contains(screen.getByTestId("conversation"))).toBe(true);
    // Not beside: the store neither opens the panel by itself nor keeps it open over a quote.
    expect(panel.besideConversation).toBe(false);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("offers no maximise over the conversation, since it already covers it", async () => {
    const panel = store();
    renderInApp(<Harness store={panel} contents={{ ...EMPTY_CONTENTS, uploads: [upload] }} />);
    act(() => reportResize(row(), { width: 1200 }));
    act(() => panel.open(upload));
    await screen.findByRole("complementary", { name: "Förhandsgranskning av fil" });
    expect(screen.getByRole("button", { name: "Maximera" })).toBeTruthy();

    act(() => reportResize(row(), { width: 420 }));
    expect(screen.queryByRole("button", { name: "Maximera" })).toBeNull();
    expect(panelRegion("Förhandsgranskning av fil").className).toContain("absolute");
  });

  it("keeps the panel, and the focus in it, when the region is resized across the threshold", () => {
    const panel = store();
    renderInApp(<Harness store={panel} />);
    act(() => reportResize(row(), { width: 420 }));
    fireEvent.click(screen.getByRole("button", { name: "Aktivitet" }));
    const aside = panelRegion();
    const step = screen.getByRole("button", { name: "Steg" });
    act(() => step.focus());

    act(() => reportResize(row(), { width: 1200 }));
    expect(panelRegion()).toBe(aside);
    expect(aside.className).toContain("relative");
    expect(screen.getByRole("separator")).toBeTruthy();
    expect(document.activeElement).toBe(step);
    expect(panel.besideConversation).toBe(true);
  });

  it("closes the covering panel on Escape", () => {
    renderInApp(<Harness store={store()} />);
    act(() => reportResize(row(), { width: 420 }));
    const toggle = screen.getByRole("button", { name: "Aktivitet" });
    fireEvent.click(toggle);
    const step = screen.getByRole("button", { name: "Steg" });

    fireEvent.keyDown(step, { key: "Escape" });
    expect(screen.queryByRole("complementary")).toBeNull();
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
  });

  it("opens the overview from its button over the conversation, and focuses it", async () => {
    const panel = store();
    renderInApp(<Harness store={panel} contents={{ ...EMPTY_CONTENTS, uploads: [upload] }} />);
    act(() => reportResize(row(), { width: 420 }));
    const launcherName = "Visa sidopanelen med filer och vyer";
    fireEvent.click(screen.getByRole("button", { name: launcherName }));

    const aside = panelRegion("Filer och vyer");
    expect(aside.className).toContain("absolute");
    await waitFor(() => expect(document.activeElement).toBe(aside));
    expect(screen.getByText(/underlag/)).toBeTruthy();

    // The button is back above the conversation (it leaves while the panel
    // shows), and gets the focus.
    fireEvent.click(screen.getByRole("button", { name: "Stäng sidopanelen med filer och vyer" }));
    expect(screen.queryByRole("complementary")).toBeNull();
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("button", { name: launcherName }))
    );
  });

  it("is a bottom sheet on a phone, whatever the region", async () => {
    setViewport("phone");
    renderInApp(<Harness store={store()} />);
    act(() => reportResize(row(), { width: 390 }));
    fireEvent.click(screen.getByRole("button", { name: "Aktivitet" }));
    expect(await screen.findByRole("dialog", { name: "Aktivitet för svaret" })).toBeTruthy();
    expect(screen.queryByRole("complementary")).toBeNull();
  });

  it("has no axe violations over the conversation", async () => {
    renderInApp(<Harness store={store()} contents={{ ...EMPTY_CONTENTS, uploads: [upload] }} />);
    act(() => reportResize(row(), { width: 420 }));
    fireEvent.click(screen.getByRole("button", { name: "Aktivitet" }));
    panelRegion();
    await expectNoAxeViolations(document.body);
  });
});
