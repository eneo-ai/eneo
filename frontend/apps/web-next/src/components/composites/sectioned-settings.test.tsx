// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";
import { ShieldCheck, SlidersHorizontal, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { router, setRoute } from "@/test/navigation";
import { renderInApp } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
import { SaveStatusProvider, useSetSaveStatus } from "./save-status";
import { SectionedSettings, type SettingsSection } from "./sectioned-settings";

vi.mock("next/navigation", () => import("@/test/navigation"));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

const sections = [
  { id: "general", label: "Allmänt", icon: SlidersHorizontal, node: <h2>Allmänt</h2> },
  { id: "ai", label: "AI", icon: Sparkles, node: <h2>AI</h2> },
  {
    id: "security",
    label: "Säkerhet och integritet",
    icon: ShieldCheck,
    node: <h2>Säkerhet och integritet</h2>
  }
];

describe("SectionedSettings", () => {
  it("keeps navigation and content in the same section order and marks the selected anchor", () => {
    renderInApp(
      <SectionedSettings navigationLabel="Avsnitt" header={<h1>Redigera</h1>} sections={sections} />
    );

    const navigation = screen.getByRole("navigation", { name: "Avsnitt" });
    const links = within(navigation).getAllByRole("link");
    const generalLink = within(navigation).getByRole("link", { name: "Allmänt" });
    const aiLink = within(navigation).getByRole("link", { name: "AI" });
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "#general",
      "#ai",
      "#security"
    ]);
    expect(generalLink.getAttribute("aria-current")).toBe("true");
    expect(document.querySelectorAll("#general")).toHaveLength(1);
    expect(document.querySelectorAll("#ai")).toHaveLength(1);

    fireEvent.click(aiLink);
    expect(aiLink.getAttribute("aria-current")).toBe("true");
    expect(generalLink.hasAttribute("aria-current")).toBe(false);
  });

  it("is an Astryx tab strip: one tab stop, arrow keys, and overflow that scrolls with fades", () => {
    const { container } = renderInApp(
      <SectionedSettings navigationLabel="Avsnitt" header={<h1>Redigera</h1>} sections={sections} />
    );
    const navigation = screen.getByRole("navigation", { name: "Avsnitt" });
    const current = within(navigation).getByRole("link", { name: "Allmänt" });
    const others = within(navigation)
      .getAllByRole("link")
      .filter((link) => link !== current);
    expect(current.getAttribute("tabindex")).toBe("0");
    expect(others.every((link) => link.getAttribute("tabindex") === "-1")).toBe(true);

    current.focus();
    fireEvent.keyDown(current, { key: "ArrowRight" });
    expect(document.activeElement).toBe(within(navigation).getByRole("link", { name: "AI" }));

    // Astryx's scrolling strip (edge fades, current tab kept in view), so a
    // long label is never truncated: it keeps its full accessible name.
    expect(container.querySelector(".astryx-tab-strip")).toBeTruthy();
    expect(within(navigation).getByRole("link", { name: "Säkerhet och integritet" })).toBeTruthy();
  });

  it("has no axe violations", async () => {
    const { container } = renderInApp(
      <SectionedSettings navigationLabel="Avsnitt" header={<h1>Redigera</h1>} sections={sections} />
    );
    await expectNoAxeViolations(container);
  });
});

/** A field whose typed text lives in its own state, as an editor section's draft does. */
function Draft() {
  const [value, setValue] = useState("");
  return (
    <input
      aria-label="Beskrivning"
      value={value}
      onChange={(event) => setValue(event.target.value)}
    />
  );
}

/** A field whose save failed: the save status links to it by id. */
function FailedField() {
  const setStatus = useSetSaveStatus();
  useEffect(() => setStatus?.("ai-model", "error"), [setStatus]);
  return <input id="ai-model" aria-label="Modell" />;
}

const EDIT = "/spaces/s1/assistants/a1/edit";

const phoneSections: SettingsSection[] = [
  {
    id: "general",
    label: "Allmänt",
    icon: SlidersHorizontal,
    group: "Innehåll",
    summary: "Ingen beskrivning",
    node: (
      <section>
        <h2>Allmänt</h2>
        <Draft />
      </section>
    )
  },
  {
    id: "ai",
    label: "AI-inställningar",
    icon: Sparkles,
    group: "Modell och funktioner",
    summary: "GPT-OSS 120B",
    node: (
      <section>
        <h2>AI-inställningar</h2>
        <FailedField />
      </section>
    )
  },
  {
    id: "security",
    label: "Säkerhet och integritet",
    icon: ShieldCheck,
    group: "Åtkomst",
    node: <h2>Säkerhet och integritet</h2>
  }
];

function renderEditor(phone: { openFirst?: string } = {}) {
  return renderInApp(
    <SaveStatusProvider>
      <SectionedSettings
        navigationLabel="Avsnitt"
        header={<h1>Min assistent</h1>}
        sections={phoneSections}
        phone={{
          parent: { label: "Assistenter", href: "/spaces/s1/assistants" },
          title: "Min assistent",
          ...phone
        }}
      />
    </SaveStatusProvider>
  );
}

const view = () => document.querySelector("[data-editor-view]")?.getAttribute("data-editor-view");
const current = () =>
  [...document.querySelectorAll("[data-editor-section][data-current]")].map((element) =>
    element.getAttribute("data-editor-section")
  );
const index = () => document.querySelector<HTMLElement>("[data-editor-index]")!;

describe("SectionedSettings on a phone (decision 21)", () => {
  it("opens on an index: the sections as rows in groups, each with what it holds now", async () => {
    setRoute(EDIT);
    const { container } = renderEditor();

    expect(view()).toBe("index");
    expect(current()).toEqual([]);
    const rows = within(index()).getAllByRole("link");
    expect(rows.map((row) => row.getAttribute("href"))).toEqual([
      `${EDIT}?section=general`,
      `${EDIT}?section=ai`,
      `${EDIT}?section=security`
    ]);
    // The summary is read once, as part of the row's name.
    expect(rows.map((row) => row.textContent)).toEqual([
      "Allmänt, Ingen beskrivning",
      "AI-inställningar, GPT-OSS 120B",
      "Säkerhet och integritet"
    ]);
    expect(
      within(index())
        .getAllByRole("heading", { level: 2 })
        .map((h) => h.textContent)
    ).toEqual(["Innehåll", "Modell och funktioner", "Åtkomst"]);
    // Every section is there once, mounted, whichever view shows.
    for (const id of ["general", "ai", "security"]) {
      expect(document.querySelectorAll(`[data-editor-section="${id}"]`)).toHaveLength(1);
    }
    // The page bar goes back to the list, and the resource's name is the h1.
    const bar = container.querySelector("[data-phone-page-bar]")!;
    expect(
      within(bar as HTMLElement)
        .getByRole("link", { name: "Tillbaka till Assistenter" })
        .getAttribute("href")
    ).toBe("/spaces/s1/assistants");
    expect(
      screen.getAllByRole("heading", { level: 1 }).some((h) => h.textContent === "Min assistent")
    ).toBe(true);
    await expectNoAxeViolations(container);
  });

  it("opens a section in place and goes back to the index with what was typed still there", () => {
    setRoute(EDIT);
    const push = vi.spyOn(window.history, "pushState");
    const back = vi.spyOn(window.history, "back").mockImplementation(() => {});
    renderEditor();
    const draft = screen.getByRole("textbox", { name: "Beskrivning" });

    const row = within(index()).getByRole("link", { name: /^Allmänt/ });
    // Handled in place: no server round trip, a history entry the system back pops.
    expect(fireEvent.click(row)).toBe(false);
    expect(new URL(String(push.mock.lastCall?.[2]), "http://localhost").search).toBe(
      "?section=general"
    );
    expect(router.push).not.toHaveBeenCalled();
    expect(view()).toBe("section");
    expect(current()).toEqual(["general"]);
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Allmänt" }));

    fireEvent.change(draft, { target: { value: "Svarar på frågor om bygglov" } });
    const bar = document.querySelector<HTMLElement>("[data-phone-page-bar]")!;
    const toIndex = within(bar).getByRole("link", { name: "Tillbaka till Min assistent" });
    expect(fireEvent.click(toIndex)).toBe(false);

    expect(back).toHaveBeenCalledTimes(1);
    expect(view()).toBe("index");
    // Nothing remounted: the same field, with the draft.
    expect(screen.getByRole("textbox", { name: "Beskrivning" })).toBe(draft);
    expect((draft as HTMLInputElement).value).toBe("Svarar på frågor om bygglov");
    expect(document.activeElement).toBe(row);
  });

  it("follows the address: ?section= opens that section, the system back the index", () => {
    setRoute(`${EDIT}?section=ai`);
    window.history.replaceState(null, "", `${EDIT}?section=ai`);
    renderEditor();
    expect(current()).toEqual(["ai"]);

    // The system back lands on the editor's own address.
    act(() => {
      window.history.replaceState(null, "", EDIT);
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(view()).toBe("index");

    cleanup();
    setRoute(`${EDIT}?section=bogus`);
    renderEditor();
    expect(view()).toBe("index");
  });

  it("opens a resource just created on the section it names, and Back replaces the address", () => {
    setRoute(EDIT);
    const replace = vi.spyOn(window.history, "replaceState");
    const back = vi.spyOn(window.history, "back");
    renderEditor({ openFirst: "general" });
    expect(current()).toEqual(["general"]);

    const bar = document.querySelector<HTMLElement>("[data-phone-page-bar]")!;
    fireEvent.click(within(bar).getByRole("link", { name: "Tillbaka till Min assistent" }));
    // Nothing was pushed to go back to: the editor's own address stays.
    expect(back).not.toHaveBeenCalled();
    expect(new URL(String(replace.mock.lastCall?.[2]), "http://localhost").pathname).toBe(EDIT);
    expect(view()).toBe("index");
  });

  it("opens the section of a field whose save failed, from the save status's link", async () => {
    setViewport("phone");
    setRoute(EDIT);
    vi.spyOn(window.history, "pushState");
    renderEditor();
    // The phone's strip shows the save state; its link names the field.
    const strip = document.querySelector<HTMLElement>("[data-editor-strip]")!;
    const failed = await within(strip).findByRole("link", { name: /Kunde inte spara/ });
    act(() => {
      fireEvent.click(failed);
    });
    expect(current()).toEqual(["ai"]);
    expect(document.activeElement).toBe(screen.getByRole("textbox", { name: "Modell" }));
  });

  it("keeps the view through a move that only changes the hash (a skip link)", () => {
    setRoute(EDIT);
    window.history.replaceState(null, "", EDIT);
    renderEditor({ openFirst: "general" });
    act(() => {
      window.history.pushState(null, "", `${EDIT}#main-content`);
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(current()).toEqual(["general"]);
  });

  it("goes back with the system back, focus on the row it came from", () => {
    setRoute(EDIT);
    window.history.replaceState(null, "", EDIT);
    renderEditor();
    fireEvent.click(within(index()).getByRole("link", { name: /^AI-inställningar/ }));
    act(() => {
      window.history.replaceState(null, "", EDIT);
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(view()).toBe("index");
    expect(document.activeElement).toBe(
      within(index()).getByRole("link", { name: /^AI-inställningar/ })
    );
  });

  it("pops the entry it opened a section into, after a reload too", () => {
    // A reload keeps the entry's state: it was opened from the index.
    setRoute(`${EDIT}?section=ai`);
    window.history.replaceState({ settingsSectionFromIndex: true }, "", `${EDIT}?section=ai`);
    const back = vi.spyOn(window.history, "back").mockImplementation(() => {});
    renderEditor();
    const bar = document.querySelector<HTMLElement>("[data-phone-page-bar]")!;
    fireEvent.click(within(bar).getByRole("link", { name: "Tillbaka till Min assistent" }));
    expect(back).toHaveBeenCalledTimes(1);
  });

  it("focuses a failed field in the section in view without a history entry", async () => {
    setViewport("phone");
    setRoute(`${EDIT}?section=ai`);
    window.history.replaceState(null, "", `${EDIT}?section=ai`);
    const push = vi.spyOn(window.history, "pushState");
    renderEditor();
    // On a section the save state sits in the page bar, in a word or two.
    const bar = document.querySelector<HTMLElement>("[data-phone-page-bar]")!;
    const failed = await within(bar).findByRole("link", { name: "Kunde inte spara" });
    expect(fireEvent.click(failed)).toBe(false);
    expect(push).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(screen.getByRole("textbox", { name: "Modell" }));
  });

  it("opens the index when the section in view goes, and does not bring it back", () => {
    setRoute(`${EDIT}?section=ai`);
    const props = {
      navigationLabel: "Avsnitt",
      header: <h1>Min assistent</h1>,
      phone: {
        parent: { label: "Assistenter", href: "/spaces/s1/assistants" },
        title: "Min assistent"
      }
    };
    const { rerender } = renderInApp(
      <SaveStatusProvider>
        <SectionedSettings {...props} sections={phoneSections} />
      </SaveStatusProvider>
    );
    expect(current()).toEqual(["ai"]);
    // A permission changed: the section is gone, then back.
    for (const sections of [
      phoneSections.filter((section) => section.id !== "ai"),
      phoneSections
    ]) {
      rerender(
        <SaveStatusProvider>
          <SectionedSettings {...props} sections={sections} />
        </SaveStatusProvider>
      );
      expect(view()).toBe("index");
    }
  });

  it("focuses the heading of a section whose own save failed", async () => {
    setViewport("phone");
    setRoute(EDIT);
    window.history.replaceState(null, "", EDIT);
    vi.spyOn(window.history, "pushState");
    function FailedSection() {
      const setStatus = useSetSaveStatus();
      useEffect(() => setStatus?.("security", "error"), [setStatus]);
      return <h2>Säkerhet och integritet</h2>;
    }
    renderInApp(
      <SaveStatusProvider>
        <SectionedSettings
          navigationLabel="Avsnitt"
          header={<h1>Min assistent</h1>}
          sections={[
            phoneSections[0]!,
            { ...phoneSections[1]!, node: <h2>AI-inställningar</h2> },
            { ...phoneSections[2]!, node: <FailedSection /> }
          ]}
          phone={{
            parent: { label: "Assistenter", href: "/spaces/s1/assistants" },
            title: "Min assistent"
          }}
        />
      </SaveStatusProvider>
    );
    // The error names the section itself (its key is the section's id).
    const strip = document.querySelector<HTMLElement>("[data-editor-strip]")!;
    fireEvent.click(await within(strip).findByRole("link", { name: /Kunde inte spara/ }));
    expect(current()).toEqual(["security"]);
    expect(document.activeElement).toBe(
      screen.getByRole("heading", { name: "Säkerhet och integritet" })
    );
  });

  it("leaves a settings page without the phone index as it was", () => {
    renderInApp(
      <SectionedSettings navigationLabel="Avsnitt" header={<h1>Redigera</h1>} sections={sections} />
    );
    expect(document.querySelector("[data-editor-view]")).toBeNull();
    expect(document.querySelector("[data-editor-index]")).toBeNull();
    expect(document.querySelector("[data-phone-page-bar]")).toBeNull();
  });
});
