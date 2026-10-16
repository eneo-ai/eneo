// @vitest-environment jsdom
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { MessageFiles, PendingMessageFiles, summarizeFiles } from "./message-files";
import { SidePanelStore } from "./side-panel/side-panel-store";
import { SidePanelProvider, useSidePanel } from "./side-panel/use-side-panel";

vi.mock("@/features/workspace/preview/load-preview", () => ({
  loadPreview: vi.fn(async () => ({ kind: "text", text: "Ready", truncated: false })),
  PreviewTooLargeError: class extends Error {}
}));

afterEach(cleanup);

const pdf = (index: number): Schema<"FilePublic"> => ({
  id: `file-${index}`,
  name: `Policy ${index}.pdf`,
  mimetype: "application/pdf",
  size: 2_048,
  original_size: 20_480
});

/** Lets a test read the panel the files rendered under. */
let panel: SidePanelStore | null = null;
function PanelSpy({ onPanel }: { onPanel: (store: SidePanelStore | null) => void }) {
  const store = useSidePanel();
  useEffect(() => onPanel(store), [store, onPanel]);
  return null;
}

function renderWithPanel(files: Schema<"FilePublic">[]) {
  return renderInApp(
    <SidePanelProvider>
      <PanelSpy
        onPanel={(store) => {
          panel = store;
        }}
      />
      <MessageFiles files={files} />
    </SidePanelProvider>
  );
}

describe("MessageFiles", () => {
  it("shows up to three documents as chips that open the file in the panel", () => {
    renderWithPanel([pdf(1), pdf(2), pdf(3)]);
    const chips = screen.getAllByRole("button", { name: /^Förhandsgranska/ });
    expect(chips).toHaveLength(3);
    expect(screen.getAllByText("PDF · 20 kB")).toHaveLength(3);
    fireEvent.click(chips[0]!);
    expect(panel?.occupant).toEqual({ kind: "file" });
    expect(panel?.file?.id).toBe("file-1");
    expect(chips[0]!.getAttribute("aria-expanded")).toBe("true");
  });

  it("bundles four or more documents and opens the panel on its uploads", () => {
    renderWithPanel([pdf(1), pdf(2), pdf(3), pdf(4), pdf(5)]);
    expect(screen.queryByRole("button", { name: /^Förhandsgranska/ })).toBeNull();
    const bundle = screen.getByRole("button", {
      name: "Öppna de 5 bifogade filerna i panelen"
    });
    expect(bundle.textContent).toContain("5 bifogade filer");
    expect(bundle.textContent).toContain("Policy 1.pdf, Policy 2.pdf, Policy 3.pdf…");
    expect(bundle.textContent).toContain("PDF 5");
    expect(bundle.textContent).toContain("Visa i panelen");
    expect(bundle.getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(bundle);
    expect(panel?.occupant).toEqual({ kind: "overview", section: "uploads" });
    expect(bundle.getAttribute("aria-expanded")).toBe("true");
    expect(bundle.textContent).toContain("Visas i panelen");

    // The bundle toggles: pressing it again closes the overview and keeps focus.
    bundle.focus();
    fireEvent.click(bundle);
    expect(panel?.occupant).toEqual({ kind: "closed" });
    expect(document.activeElement).toBe(bundle);
  });

  it("unfolds the bundle in place where there is no panel", () => {
    renderInApp(<MessageFiles files={[pdf(1), pdf(2), pdf(3), pdf(4)]} />);
    const bundle = screen.getByRole("button", { name: "Öppna de 4 bifogade filerna i panelen" });
    expect(bundle.textContent).toContain("Visa");
    fireEvent.click(bundle);
    expect(screen.getAllByRole("button", { name: /^Förhandsgranska/ })).toHaveLength(4);
    expect(bundle.textContent).toContain("Visa färre");
  });

  it("has no axe violations as chips and as a bundle", async () => {
    const { container } = renderWithPanel([pdf(1), pdf(2), pdf(3), pdf(4)]);
    await expectNoAxeViolations(container);
    cleanup();
    const { container: chips } = renderWithPanel([pdf(1)]);
    await expectNoAxeViolations(chips);
  });
});

describe("PendingMessageFiles", () => {
  const upload = (index: number, uploading: boolean) => ({
    key: `key-${index}`,
    name: `Policy ${index}.pdf`,
    size: 2_048,
    mimetype: "application/pdf",
    uploading
  });

  it("shows few uploads as chips that say whether they are done", () => {
    renderInApp(<PendingMessageFiles uploads={[upload(1, true), upload(2, false)]} />);
    const list = screen.getByRole("list", { name: "Bilagor" });
    expect(list.textContent).toContain("Policy 1.pdf");
    expect(list.textContent).toContain("Laddar upp…");
    expect(list.textContent).toContain("PDF · 2 kB");
  });

  it("shows many uploads as one bundle with their progress", async () => {
    const { container } = renderInApp(
      <PendingMessageFiles
        uploads={[upload(1, false), upload(2, false), upload(3, true), upload(4, true)]}
      />
    );
    expect(screen.getByText("4 bifogade filer")).toBeTruthy();
    expect(screen.getByText("2 av 4 klara")).toBeTruthy();
    const bar = screen.getByRole("progressbar", { name: "Laddar upp..." });
    expect(bar.getAttribute("aria-valuenow")).toBe("2");
    expect(bar.getAttribute("aria-valuemax")).toBe("4");
    await expectNoAxeViolations(container);
  });
});

describe("summarizeFiles", () => {
  it("names the first files, counts the types and sums the sizes", () => {
    expect(
      summarizeFiles(
        [
          { name: "a.pdf", size: 1024 },
          { name: "b.docx", size: 1024 },
          { name: "c.pdf", size: 1024 },
          { name: "d", size: 1024 }
        ],
        "Okänd",
        "sv"
      )
    ).toBe("a.pdf, b.docx, c.pdf… · PDF 2 · DOCX 1 · Okänd 1 · 4 kB");
  });
});
