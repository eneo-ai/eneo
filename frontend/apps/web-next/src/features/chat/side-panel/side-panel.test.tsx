// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { Workflow } from "lucide-react";
import { useState, useSyncExternalStore } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
import { PanelFrame } from "./panel-frame";
import { SidePanel, type OccupantFrame } from "./side-panel";
import { SidePanelStore } from "./side-panel-store";

const EMPTY_CONTENTS = { views: [], documents: [], uploads: [] };

/** A flow page: the flow as the native content, the conversation as its companion. */
function Harness({ companion = true }: { companion?: boolean }) {
  const [panel] = useState(() => new SidePanelStore(() => Promise.reject(new Error("unused"))));
  // The conversation view re-renders the panel on every store change.
  useSyncExternalStore(panel.subscribe, panel.getVersion, panel.getVersion);
  const body = (frame: OccupantFrame) => (
    <PanelFrame
      icon={<Workflow className="size-4" />}
      title="Ärendeberedning"
      detail="5 steg · Utkast"
      switcher={frame.switcher}
      maximise={frame.maximise}
      headingLevel={frame.headingLevel}
      onClose={frame.primary ? undefined : () => panel.closeNative()}
    >
      <p>Flödets steg</p>
    </PanelFrame>
  );
  return (
    <SidePanel
      panel={panel}
      messages={[]}
      contents={EMPTY_CONTENTS}
      versionsOf={() => []}
      exportOf={() => null}
      native={{ label: "Flödespanel", body }}
      companion={
        companion
          ? { label: "Chatt med Flödesassistenten", identity: <span>Flödesassistenten</span> }
          : null
      }
      activity={null}
      latestActivity={null}
    >
      <p>Konversationen</p>
    </SidePanel>
  );
}

afterEach(cleanup);

describe("SidePanel with a companion conversation", () => {
  it("makes the native content the page from 1024px, the conversation a column after it", async () => {
    setViewport("desktop");
    const { container } = renderInApp(<Harness />);
    const page = screen.getByRole("complementary", { name: "Flödespanel" });
    const chat = screen.getByRole("region", { name: "Chatt med Flödesassistenten" });
    expect(within(page).getByRole("heading", { level: 1, name: "Ärendeberedning" })).toBeTruthy();
    expect(page.compareDocumentPosition(chat) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // The page's content is not closed, and Escape leaves it alone.
    expect(within(page).queryByRole("button", { name: "Stäng" })).toBeNull();
    fireEvent.keyDown(page, { key: "Escape" });
    expect(screen.getByText("Flödets steg")).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("folds the conversation away from either header and shows it again", () => {
    setViewport("desktop");
    renderInApp(<Harness />);
    const page = screen.getByRole("complementary", { name: "Flödespanel" });
    const chat = screen.getByRole("region", { name: "Chatt med Flödesassistenten" });

    fireEvent.click(within(chat).getByRole("button", { name: "Dölj chatten" }));
    expect(chat.hidden).toBe(true);
    expect(document.activeElement).toBe(page);

    const show = within(page).getByRole("button", { name: "Visa chatten" });
    expect(show.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(show);
    expect(chat.hidden).toBe(false);
    const hide = within(page).getByRole("button", { name: "Dölj chatten" });
    expect(hide.getAttribute("aria-controls")).toBe(chat.id);
  });

  it("keeps the conversation as the page below 1024px, the flow in a sheet when asked for", () => {
    setViewport("phone");
    renderInApp(<Harness />);
    expect(screen.getByText("Konversationen")).toBeTruthy();
    expect(screen.queryByText("Flödets steg")).toBeNull();
    expect(screen.queryByRole("region", { name: "Chatt med Flödesassistenten" })).toBeNull();
  });
});
