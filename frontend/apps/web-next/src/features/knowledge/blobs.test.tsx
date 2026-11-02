// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { API_BASE } from "@/lib/api/base";
import { toast } from "@/lib/toast";
import type { InfoBlob } from "./knowledge";

const api = vi.hoisted(() => ({
  GET: vi.fn(),
  POST: vi.fn()
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { recordFinishedJob, resetRecentResults } from "@/features/jobs/recent-results";
import type { Job } from "@/features/jobs/jobs";
import { AddTextDialog, BlobPreviewDialog, BlobTable } from "./blobs";

afterEach(() => {
  cleanup();
  resetRecentResults();
  vi.clearAllMocks();
  vi.restoreAllMocks();
  api.GET.mockReset();
});

const apiResult = (data: unknown) => ({ data, response: new Response("{}") });

const blob = (id: string, title: string, size: number) =>
  ({ id, metadata: { title, size } }) as unknown as InfoBlob;

const names = () =>
  within(screen.getByRole("table"))
    .getAllByRole("button", { name: /^\S+\.pdf$/ })
    .map((button) => button.textContent);

describe("BlobPreviewDialog downloads", () => {
  it("shows a refused original download and permits retry without closing the preview", async () => {
    api.GET.mockResolvedValue(apiResult({ text: "text", original_available: true }));
    api.POST.mockResolvedValueOnce({
      error: { message: "Forbidden" },
      response: new Response("", { status: 403 })
    });
    const error = vi.spyOn(toast, "error");
    const close = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    renderInApp(
      <BlobPreviewDialog blob={blob("1", "rapport.pdf", 10)} open onOpenChange={close} />
    );
    fireEvent.click(await screen.findByRole("button", { name: "Ladda ner original" }));
    await waitFor(() => expect(error).toHaveBeenCalled());
    expect(close).not.toHaveBeenCalled();
    expect(click).not.toHaveBeenCalled();
    api.POST.mockResolvedValueOnce(
      apiResult({
        url: "http://backend:8000/api/v1/info-blobs/1/original/download/?token=capability"
      })
    );
    fireEvent.click(await screen.findByRole("button", { name: "Ladda ner original" }));
    await waitFor(() => expect(click).toHaveBeenCalledTimes(1));
  });
  it("downloads the available original once, with a busy button that retains focus", async () => {
    api.GET.mockResolvedValue(apiResult({ text: "text", original_available: true }));
    let finish!: (value: unknown) => void;
    api.POST.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      })
    );
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    renderInApp(
      <BlobPreviewDialog blob={blob("1", "rapport.pdf", 10)} open onOpenChange={() => {}} />
    );
    const download = await screen.findByRole("button", { name: "Ladda ner original" });
    download.focus();
    fireEvent.click(download);
    await waitFor(() => expect(download.getAttribute("aria-busy")).toBe("true"));
    expect(document.activeElement).toBe(download);
    expect(download.hasAttribute("disabled")).toBe(false);
    fireEvent.click(download);
    expect(api.POST).toHaveBeenCalledTimes(1);
    expect(api.POST).toHaveBeenCalledWith("/api/v1/info-blobs/{id}/original/signed-url/", {
      params: { path: { id: "1" } },
      body: { expires_in: 3600, content_disposition: "attachment" },
      signal: expect.any(AbortSignal)
    });
    await act(async () =>
      finish(
        apiResult({
          url: "http://backend:8000/api/v1/info-blobs/1/original/download/?token=capability"
        })
      )
    );
    expect(click).toHaveBeenCalledTimes(1);
    expect((click.mock.contexts[0] as HTMLAnchorElement).getAttribute("href")).toBe(
      `${API_BASE}/api/v1/info-blobs/1/original/download/?token=capability`
    );
  });

  it("does not start a late original download after the preview unmounts", async () => {
    api.GET.mockResolvedValue(apiResult({ text: "text", original_available: true }));
    let finish!: (value: unknown) => void;
    api.POST.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      })
    );
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const view = renderInApp(
      <BlobPreviewDialog blob={blob("1", "rapport.pdf", 10)} open onOpenChange={() => {}} />
    );
    fireEvent.click(await screen.findByRole("button", { name: "Ladda ner original" }));
    const signal = api.POST.mock.calls[0]![1].signal as AbortSignal;
    view.unmount();
    expect(signal.aborted).toBe(true);
    await act(async () =>
      finish(
        apiResult({
          url: "http://backend:8000/api/v1/info-blobs/1/original/download/?token=capability"
        })
      )
    );
    expect(click).not.toHaveBeenCalled();
  });

  it("saves extracted text as plain UTF-8 with a single txt extension", async () => {
    api.GET.mockResolvedValue(
      apiResult({ text: "Årsrapport <script>text</script>", original_available: false })
    );
    const create = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:extracted");
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    renderInApp(
      <BlobPreviewDialog blob={blob("1", "rapport.txt", 10)} open onOpenChange={() => {}} />
    );
    const download = await screen.findByRole("button", { name: "Ladda ner extraherad text" });
    await waitFor(() => expect(download.hasAttribute("disabled")).toBe(false));
    fireEvent.click(download);
    expect(click).toHaveBeenCalledTimes(1);
    const anchor = click.mock.contexts[0] as HTMLAnchorElement;
    expect(anchor.download).toBe("rapport.txt");
    expect(anchor.getAttribute("href")).toBe("blob:extracted");
    const file = create.mock.calls[0]![0] as Blob;
    expect(file.type).toBe("text/plain;charset=utf-8");
    const text = await new Promise((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.readAsText(file);
    });
    expect(text).toBe("Årsrapport <script>text</script>");
    expect(screen.queryByRole("button", { name: "Ladda ner original" })).toBeNull();
  });
});

describe("BlobTable", () => {
  it("marks the file a job just produced as newly added", () => {
    const id = "5d1b9c1e-0b4e-4c21-9d7c-2f0f0a6d3e11";
    recordFinishedJob({
      id: "job",
      task: "upload_info_blob",
      status: "complete",
      result_location: `/api/v1/info-blobs/${id}/`
    } as Job);
    const { container } = renderInApp(
      <BlobTable
        blobs={[blob("other", "Gammal.pdf", 10), blob(id, "Ny.pdf", 20)]}
        canEdit={false}
        labelledBy="files"
      />
    );
    // Astryx's row-status plugin marks the row with a named status signifier.
    const marks = within(container).getAllByRole("img", { name: "Nyss tillagd" });
    expect(marks).toHaveLength(1);
    expect(marks[0]?.closest("tr")?.textContent).toContain("Ny.pdf");
  });

  it("fits an upright tablet, its name held in view where a phone scrolls it", () => {
    renderInApp(<BlobTable blobs={[blob("1", "a.pdf", 1)]} canEdit labelledBy="files" />);
    const table = screen.getByRole("table");
    // The Created column stays available on a phone through horizontal scrolling.
    expect(Number.parseFloat(table.style.minWidth)).toBeLessThanOrEqual(700);
    // The row-status gutter (Astryx offsets pinned cells from the start) and the name.
    const pinned = within(table)
      .getAllByRole("columnheader")
      .filter((cell) => cell.style.insetInlineStart);
    expect(pinned.at(-1)?.textContent).toBe("Namn");
  });

  it("sorts by Created and shows a website URL below its title or as its fallback", () => {
    const dated = (id: string, title: string, date: string, url: string) => ({
      ...blob(id, title, 10),
      created_at: date,
      metadata: { ...blob(id, title, 10).metadata, url }
    });
    renderInApp(
      <BlobTable
        blobs={[
          dated("new", "Ny.pdf", "2026-10-30T10:00:00Z", "https://example.test/new"),
          dated("old", "", "2026-10-01T10:00:00Z", "https://example.test/old")
        ]}
        canEdit={false}
        labelledBy="files"
      />
    );
    expect(screen.getByRole("button", { name: "https://example.test/old" })).toBeTruthy();
    expect(screen.getByText("https://example.test/new")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Sortera efter Skapad" }));
    const rows = within(screen.getByRole("table")).getAllByRole("row");
    expect(rows[1]!.textContent).toContain("https://example.test/old");
    expect(rows[2]!.querySelector("time")?.dateTime).toBe("2026-10-30T10:00:00.000Z");
  });

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
    const { container } = renderInApp(<BlobTable blobs={[]} canEdit labelledBy="files" />);
    // Worded and tinted like the collections' own empty state ("Inga samlingar ännu").
    expect(screen.getByRole("heading", { level: 2, name: "Inga filer ännu" })).toBeTruthy();
    expect(container.querySelector(".bg-ax-blue-muted")).toBeTruthy();
  });
});

describe("BlobActions", () => {
  it("keeps focus on a busy Spara ändringar and renames once", async () => {
    api.POST.mockReturnValue(new Promise(() => {}));
    renderInApp(
      <>
        <h1 id="collection-title">Upphandlingspolicy</h1>
        <BlobTable blobs={[blob("1", "a.pdf", 100)]} canEdit labelledBy="collection-title" />
      </>
    );
    fireEvent.click(screen.getByRole("button", { name: "Fler åtgärder för a.pdf" }));
    const edit = await screen.findByRole("menuitem", { name: "Redigera" });
    // The menu moves focus into itself on the next frame; let it, as a user would.
    await act(() => new Promise((resolve) => requestAnimationFrame(resolve)));
    fireEvent.click(edit);
    const dialog = await screen.findByRole("dialog", { name: "Redigera fil" });
    const save = within(dialog).getByRole("button", { name: "Spara ändringar" });
    save.focus();

    fireEvent.click(save);

    const busy = await within(dialog).findByRole("button", { name: "Sparar…" });
    expect(busy).toBe(save);
    expect(busy.getAttribute("aria-busy")).toBe("true");
    expect(busy.hasAttribute("disabled")).toBe(false);
    expect(document.activeElement).toBe(busy);
    fireEvent.click(busy);
    expect(api.POST).toHaveBeenCalledTimes(1);
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
