// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PreviewFile } from "@/features/workspace/preview/preview-kind";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { PanelContentsList } from "./panel-contents-list";
import { SidePanelStore } from "./side-panel-store";

afterEach(cleanup);

const file = (index: number, extension: string): PreviewFile => ({
  id: `file-${index}`,
  name: `Fil ${index}.${extension}`,
  mimetype: extension === "pdf" ? "application/pdf" : "text/plain",
  size: 1_024
});

function renderList(uploads: PreviewFile[]) {
  const panel = new SidePanelStore(() => Promise.resolve("/file"));
  return renderInApp(
    <PanelContentsList
      panel={panel}
      contents={{ views: [], documents: [], uploads }}
      onFile={vi.fn()}
      onView={vi.fn()}
    />
  );
}

describe("PanelContentsList uploads", () => {
  it("lists a short upload list with its count and size, without a filter", () => {
    renderList([file(1, "pdf"), file(2, "txt")]);
    const section = screen.getByRole("region", { name: "Uppladdade filer" });
    expect(within(section).getByRole("heading").textContent).toBe("Uppladdade filer · 2 · 2 kB");
    expect(within(section).queryByRole("textbox")).toBeNull();
    expect(within(section).getAllByRole("listitem")).toHaveLength(2);
  });

  it("filters a long upload list by name and by type", async () => {
    const uploads = Array.from({ length: 9 }, (_, index) =>
      file(index + 1, index < 7 ? "pdf" : "txt")
    );
    const { container } = renderList(uploads);
    const section = screen.getByRole("region", { name: "Uppladdade filer" });
    expect(within(section).getAllByRole("listitem")).toHaveLength(9);

    fireEvent.click(within(section).getByRole("button", { name: "TXT 2" }));
    expect(within(section).getAllByRole("listitem")).toHaveLength(2);

    fireEvent.change(within(section).getByRole("textbox", { name: "Filtrera filer…" }), {
      target: { value: "fil 8" }
    });
    expect(within(section).getAllByRole("listitem")).toHaveLength(1);
    expect(within(section).getByText("Fil 8.txt")).toBeTruthy();

    fireEvent.click(within(section).getByRole("button", { name: "Alla 9" }));
    expect(within(section).getAllByRole("listitem")).toHaveLength(1);

    fireEvent.change(within(section).getByRole("textbox", { name: "Filtrera filer…" }), {
      target: { value: "ingen" }
    });
    expect(within(section).queryAllByRole("listitem")).toHaveLength(0);
    expect(within(section).getByText("Inga filer matchar")).toBeTruthy();
    await expectNoAxeViolations(container);
  });
});
