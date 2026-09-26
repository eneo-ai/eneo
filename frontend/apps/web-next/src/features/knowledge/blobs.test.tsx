// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { InfoBlob } from "./knowledge";

const api = vi.hoisted(() => ({
  GET: () => Promise.resolve({ data: { text: "" }, response: new Response("{}") }),
  POST: vi.fn()
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { AddTextDialog, BlobTable } from "./blobs";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const blob = (id: string, title: string, size: number) =>
  ({ id, metadata: { title, size } }) as unknown as InfoBlob;

const names = () =>
  within(screen.getByRole("table"))
    .getAllByRole("button", { name: /^\S+\.pdf$/ })
    .map((button) => button.textContent);

describe("BlobTable", () => {
  it("keeps the upload order until a header sorts it", async () => {
    const { container } = renderInApp(
      <>
        <h1 id="collection-title">Upphandlingspolicy</h1>
        <BlobTable
          blobs={[blob("1", "b.pdf", 300), blob("2", "ö.pdf", 100), blob("3", "a.pdf", 200)]}
          canEdit
          labelledBy="collection-title"
        />
      </>
    );

    // Named by what the page shows it under (here the collection's title).
    expect(screen.getByRole("table", { name: "Upphandlingspolicy" })).toBeTruthy();
    expect(names()).toEqual(["b.pdf", "ö.pdf", "a.pdf"]);
    fireEvent.click(screen.getByRole("button", { name: "Sortera efter Storlek" }));
    expect(names()).toEqual(["ö.pdf", "a.pdf", "b.pdf"]);
    fireEvent.click(screen.getByRole("button", { name: "Sortera efter Namn" }));
    expect(names()).toEqual(["a.pdf", "b.pdf", "ö.pdf"]);
    expect(screen.getAllByRole("button", { name: /Fler åtgärder för/ })).toHaveLength(3);
    await expectNoAxeViolations(container);
  });

  it("pages through more than 100 files and filters by name", () => {
    const blobs = Array.from({ length: 105 }, (_, index) =>
      blob(String(index), `fil-${String(index).padStart(3, "0")}.pdf`, index)
    );
    renderInApp(<BlobTable blobs={blobs} canEdit={false} labelledBy="files" />);

    expect(names()).toHaveLength(100);
    const pages = screen.getByRole("navigation", { name: /Bläddra bland filer/ });
    expect(pages).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Fler åtgärder för/ })).toBeNull();

    fireEvent.change(screen.getByRole("textbox", { name: "Filtrera filer" }), {
      target: { value: "fil-104" }
    });
    expect(names()).toEqual(["fil-104.pdf"]);
    expect(screen.queryByRole("navigation", { name: /Bläddra bland filer/ })).toBeNull();
  });

  it("stays on a page with files when the list shrinks under it", () => {
    const files = (count: number) =>
      Array.from({ length: count }, (_, index) =>
        blob(String(index), `fil-${String(index).padStart(3, "0")}.pdf`, index)
      );
    let setBlobs: (blobs: InfoBlob[]) => void = () => {};
    function Files() {
      const [blobs, set] = useState(() => files(105));
      setBlobs = set;
      return <BlobTable blobs={blobs} canEdit={false} labelledBy="files" />;
    }
    renderInApp(<Files />);
    fireEvent.click(screen.getByRole("button", { name: "Gå till nästa sida" }));
    expect(names()).toEqual([
      "fil-100.pdf",
      "fil-101.pdf",
      "fil-102.pdf",
      "fil-103.pdf",
      "fil-104.pdf"
    ]);

    // Files deleted (or a recrawl indexed fewer pages): page 2 no longer exists.
    act(() => setBlobs(files(100)));
    expect(names()).toHaveLength(100);
    expect(names()[0]).toBe("fil-000.pdf");

    // It grew again: the pager is back, so the second page is reachable.
    act(() => setBlobs(files(103)));
    expect(screen.getByRole("navigation", { name: /Bläddra bland filer/ })).toBeTruthy();
  });

  it("explains an empty list, one level below the page's h1", () => {
    // Both pages render the table straight under their h1 (1.3.1 heading order).
    renderInApp(<BlobTable blobs={[]} canEdit labelledBy="files" />);
    expect(
      screen.getByRole("heading", { level: 2, name: "Du har inga filer uppladdade ännu" })
    ).toBeTruthy();
  });
});

describe("AddTextDialog", () => {
  it("shows what is missing at its field on submit, and keeps focus on a busy submit", async () => {
    api.POST.mockReturnValue(new Promise(() => {}));
    renderInApp(<AddTextDialog collectionId="collection-1" />);
    fireEvent.click(screen.getByRole("button", { name: "Lägg till text" }));
    const dialog = await screen.findByRole("dialog", { name: "Lägg till text" });
    const submit = within(dialog).getByRole("button", { name: "Skicka" });
    expect(submit.hasAttribute("disabled")).toBe(false);

    fireEvent.click(submit);
    const title = within(dialog).getByLabelText("Titel");
    const content = within(dialog).getByLabelText("Innehåll");
    expect(document.activeElement).toBe(title);
    expect(title.getAttribute("aria-invalid")).toBe("true");
    expect(content.getAttribute("aria-invalid")).toBe("true");
    await expectNoAxeViolations(dialog);

    fireEvent.change(title, { target: { value: "Delegationsordning" } });
    fireEvent.click(submit);
    expect(document.activeElement).toBe(content);
    expect(api.POST).not.toHaveBeenCalled();

    fireEvent.change(content, { target: { value: "Nämnden delegerar beslut om ..." } });
    submit.focus();
    fireEvent.click(submit);
    const busy = await within(dialog).findByRole("button", { name: "Skickar..." });
    expect(busy).toBe(submit);
    expect(busy.getAttribute("aria-busy")).toBe("true");
    expect(document.activeElement).toBe(busy);
    fireEvent.click(busy);
    expect(api.POST).toHaveBeenCalledTimes(1);
  });
});
