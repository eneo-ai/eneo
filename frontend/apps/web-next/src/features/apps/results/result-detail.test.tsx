// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EneoApiError } from "@/lib/api/errors";
import { printResult } from "./print-result";
import { API_BASE } from "@/lib/api/base";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testQueryClient } from "@/test/render";
import type { AppRun } from "../apps";

const api = vi.hoisted(() => ({
  POST: vi.fn(async (_path: string, options: { params: { path: { id: string } } }) => ({
    data: {
      url: `http://backend:8000/api/v1/files/${options.params.path.id}/download/?token=signed-value`
    },
    response: new Response("{}")
  }))
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
const toast = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn() }));
vi.mock("@/lib/toast", () => ({ toast }));

import { ResultDetail } from "./result-detail";

afterEach(() => {
  cleanup();
  api.POST.mockReset();
  toast.error.mockClear();
  vi.restoreAllMocks();
});

function makeRun(overrides: Partial<AppRun> = {}): AppRun {
  return {
    id: "run-1",
    created_at: "2026-09-25T08:00:00Z",
    finished_at: "2026-09-25T08:01:00Z",
    status: "complete",
    output: "Sammanfattning av intervjun",
    user: { id: "user-1", email: "anna.lind@example.se" },
    skill_provenance: [],
    input: {
      text: null,
      files: [
        {
          id: "file-1",
          name: "intervju.mp3",
          mimetype: "audio/mpeg",
          size: 42,
          transcription: "Hej och välkommen till intervjun."
        }
      ]
    },
    ...overrides
  };
}

function renderResult(run: AppRun, hideBackOnPhone?: boolean) {
  const queryClient = testQueryClient();
  queryClient.setQueryData(["app-runs", run.id], run);
  return renderInApp(
    <ResultDetail
      runId={run.id}
      backHref="/apps"
      hideBackOnPhone={hideBackOnPhone}
      newRunHref="/apps/new"
    />,
    { queryClient }
  );
}

/** The docked bar's controls, in the order they sit. */
function dockedActions() {
  const dock = screen.getByRole("group", { name: "Resultat, åtgärder" });
  return [...dock.querySelectorAll("a, button")].map(
    (control) => control.getAttribute("aria-label") ?? control.textContent
  );
}

describe("ResultDetail", () => {
  it("shows the output and the transcription as keyboard tabs, each panel named by its tab", async () => {
    const { container } = renderResult(makeRun());

    const tablist = screen.getByRole("tablist", { name: "Resultat och transkription" });
    const results = within(tablist).getByRole("tab", { name: "Resultat" });
    const transcription = within(tablist).getByRole("tab", { name: "Transkription" });
    expect(results.getAttribute("aria-selected")).toBe("true");
    expect(transcription.getAttribute("aria-selected")).toBe("false");
    // Roving tabindex: the strip is one tab stop.
    expect(results.tabIndex).toBe(0);
    expect(transcription.tabIndex).toBe(-1);

    const resultsPanel = screen.getByRole("tabpanel", { name: "Resultat" });
    expect(results.getAttribute("aria-controls")).toBe(resultsPanel.id);
    expect(within(resultsPanel).getByText("Sammanfattning av intervjun")).toBeTruthy();
    // The transcription loads its audio only once it is opened.
    expect(api.POST).not.toHaveBeenCalled();
    await expectNoAxeViolations(container);

    results.focus();
    fireEvent.keyDown(results, { key: "ArrowRight" });
    expect(document.activeElement).toBe(transcription);
    fireEvent.click(transcription);

    expect(transcription.getAttribute("aria-selected")).toBe("true");
    const transcriptionPanel = screen.getByRole("tabpanel", { name: "Transkription" });
    expect(transcription.getAttribute("aria-controls")).toBe(transcriptionPanel.id);
    expect(within(transcriptionPanel).getByText("Hej och välkommen till intervjun.")).toBeTruthy();
    expect(screen.queryByText("Sammanfattning av intervjun")).toBeNull();
    await waitFor(() =>
      expect(transcriptionPanel.querySelector("audio")?.getAttribute("src")).toBe(
        `${API_BASE}/api/v1/files/file-1/download/?token=signed-value`
      )
    );
    await expectNoAxeViolations(container);

    // The page's Kopiera and Ladda ner act on the output, so they leave with
    // it: the transcription has its own Ladda ner per file.
    expect(dockedActions()).toEqual(["Ny körning"]);

    fireEvent.keyDown(transcription, { key: "Home" });
    expect(document.activeElement).toBe(results);
  });

  it("keeps its back link on a phone unless the space's page bar has one", () => {
    renderResult(makeRun());
    const back = screen.getByRole("link", { name: "Tillbaka" });
    expect(back.getAttribute("href")).toBe("/apps");
    expect(back.className).not.toContain("max-md:hidden");
    cleanup();

    renderResult(makeRun(), true);
    expect(screen.getByRole("link", { name: "Tillbaka" }).className).toContain("max-md:hidden");
  });

  it("shows the output without tabs when nothing was transcribed", () => {
    renderResult(makeRun({ input: { text: "Vad säger avtalet?", files: [] } } as Partial<AppRun>));

    expect(screen.queryByRole("tablist")).toBeNull();
    expect(screen.getByText("Sammanfattning av intervjun")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Kopiera" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Ny körning" }).getAttribute("href")).toBe("/apps/new");
  });

  it("docks copy, print and download before the primary new-run action for a finished run", () => {
    const { container } = renderResult(makeRun());

    expect(dockedActions()).toEqual([
      "Kopiera",
      "Skriv ut / Spara utdata som PDF",
      "Ladda ner",
      "Ny körning"
    ]);
    // The input files are one line of the summary.
    expect(container.querySelector("aside")?.textContent).toContain("Indataintervju.mp3");
    // The output panel no longer repeats them.
    const panel = screen.getByRole("tabpanel", { name: "Resultat" });
    expect(within(panel).queryByRole("button", { name: "Kopiera" })).toBeNull();
    expect(screen.getByText("Slutförd")).toBeTruthy();
    // The summary's labels read like "Indata", without a colon of their own.
    expect(screen.getByText("Startad")).toBeTruthy();
    expect(screen.getByText("Avslutad")).toBeTruthy();
  });

  it("prints only the rendered output and removes the temporary document when print returns", () => {
    renderResult(makeRun());
    const print = vi.spyOn(window, "print").mockImplementation(() => {
      const document = window.document.querySelector("body > [data-app-result-print-document]");
      expect(document?.textContent).toBe("Sammanfattning av intervjun");
      expect(document?.querySelector("button, aside, audio")).toBeNull();
      expect(window.document.body.hasAttribute("data-app-result-printing")).toBe(true);
    });
    fireEvent.click(screen.getByRole("button", { name: "Skriv ut / Spara utdata som PDF" }));
    expect(print).toHaveBeenCalledOnce();
    expect(document.querySelector("[data-app-result-print-document]")).toBeNull();
    expect(document.body.hasAttribute("data-app-result-printing")).toBe(false);
  });

  it("copies, prints and downloads the selected transcription using the output filename", async () => {
    const run = makeRun();
    run.input.files.push({
      ...run.input.files[0]!,
      id: "file-2",
      name: "annan.mp3",
      transcription: "En annan transkription."
    });
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const create = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:transcription");
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    renderResult(run);
    fireEvent.click(screen.getByRole("button", { name: "Ladda ner" }));
    const outputName = (click.mock.contexts[0] as HTMLAnchorElement).download;
    expect(outputName).toBe("intervju.mp3, annan.mp3.txt");
    fireEvent.click(screen.getByRole("tab", { name: "Transkription" }));
    const section = screen.getByRole("region", { name: "annan.mp3" });
    fireEvent.click(within(section).getByRole("button", { name: "Kopiera transkription" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("En annan transkription."));
    const print = vi.spyOn(window, "print").mockImplementation(() => {
      expect(document.querySelector("body > [data-app-result-print-document]")?.textContent).toBe(
        "En annan transkription."
      );
    });
    fireEvent.click(
      within(section).getByRole("button", { name: "Skriv ut / Spara transkription som PDF" })
    );
    expect(print).toHaveBeenCalledOnce();
    fireEvent.click(
      within(section).getByRole("button", { name: "Ladda ner transkription som råtext" })
    );
    expect((click.mock.contexts[1] as HTMLAnchorElement).download).toBe(outputName);
    const text = await new Promise((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.readAsText(create.mock.calls[1]![0] as Blob);
    });
    expect(text).toBe("En annan transkription.");
  });

  it("requests a fresh attachment URL for exact original audio on each download", async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    renderResult(makeRun());
    fireEvent.click(screen.getByRole("tab", { name: "Transkription" }));
    await waitFor(() => expect(api.POST).toHaveBeenCalledOnce());
    api.POST.mockResolvedValueOnce({
      data: { url: "http://backend:8000/api/v1/files/file-1/original/download/?token=first" },
      response: new Response()
    });
    const download = screen.getByRole("button", { name: 'Ladda ner original "intervju.mp3"' });
    fireEvent.click(download);
    await waitFor(() => expect(click).toHaveBeenCalledOnce());
    expect(api.POST).toHaveBeenLastCalledWith("/api/v1/files/{id}/original/signed-url/", {
      params: { path: { id: "file-1" } },
      body: { expires_in: 3600, content_disposition: "attachment" }
    });
    expect((click.mock.contexts[0] as HTMLAnchorElement).getAttribute("href")).toBe(
      `${API_BASE}/api/v1/files/file-1/original/download/?token=first`
    );
    expect((click.mock.contexts[0] as HTMLAnchorElement).download).toBe("intervju.mp3");
    api.POST.mockResolvedValueOnce({
      data: { url: "http://backend:8000/api/v1/files/file-1/original/download/?token=second" },
      response: new Response()
    });
    fireEvent.click(download);
    await waitFor(() => expect(click).toHaveBeenCalledTimes(2));
    expect((click.mock.contexts[1] as HTMLAnchorElement).getAttribute("href")).toContain(
      "token=second"
    );
  });

  it("reports an unavailable original without downloading processed audio and allows retry", async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    renderResult(makeRun());
    fireEvent.click(screen.getByRole("tab", { name: "Transkription" }));
    await waitFor(() => expect(api.POST).toHaveBeenCalledOnce());
    api.POST.mockRejectedValueOnce(new Error("Original unavailable"));
    const download = screen.getByRole("button", { name: 'Ladda ner original "intervju.mp3"' });
    fireEvent.click(download);
    await waitFor(() => expect(toast.error).toHaveBeenCalledOnce());
    expect(click).not.toHaveBeenCalled();
    api.POST.mockResolvedValueOnce({
      data: { url: "http://backend:8000/api/v1/files/file-1/original/download/?token=retry" },
      response: new Response()
    });
    fireEvent.click(download);
    await waitFor(() => expect(click).toHaveBeenCalledOnce());
  });

  it("cleans up printing if the browser refuses the dialog", () => {
    renderResult(makeRun());
    const content = screen.getByRole("tabpanel", { name: "Resultat" });
    vi.spyOn(window, "print").mockImplementation(() => {
      throw new Error("Print unavailable");
    });
    expect(() => printResult(content)).toThrow("Print unavailable");
    expect(document.querySelector("[data-app-result-print-document]")).toBeNull();
    expect(document.body.hasAttribute("data-app-result-printing")).toBe(false);
    expect(screen.getByRole("tab", { name: "Resultat" })).toBeTruthy();
  });

  it("refuses an unexpected original download path and shows its error without following it", async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    renderResult(makeRun());
    fireEvent.click(screen.getByRole("tab", { name: "Transkription" }));
    await waitFor(() => expect(api.POST).toHaveBeenCalledOnce());
    api.POST.mockResolvedValueOnce({
      data: { url: "https://example.org/wrong?token=value" },
      response: new Response()
    });
    fireEvent.click(screen.getByRole("button", { name: 'Ladda ner original "intervju.mp3"' }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledOnce());
    expect(click).not.toHaveBeenCalled();
  });

  it("keeps the backend's original-audio refusal and trace id", async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    renderResult(makeRun());
    fireEvent.click(screen.getByRole("tab", { name: "Transkription" }));
    await waitFor(() => expect(api.POST).toHaveBeenCalledOnce());
    api.POST.mockRejectedValueOnce(
      new EneoApiError("Originalet är inte tillgängligt", {
        status: 404,
        traceId: "original-trace"
      })
    );
    fireEvent.click(screen.getByRole("button", { name: 'Ladda ner original "intervju.mp3"' }));
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Originalet är inte tillgängligt",
        expect.objectContaining({ description: expect.stringContaining("original-trace") })
      )
    );
    expect(click).not.toHaveBeenCalled();
  });

  it("delivers an explicitly requested download after leaving the tab while ignoring repeated clicks", async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    renderResult(makeRun());
    fireEvent.click(screen.getByRole("tab", { name: "Transkription" }));
    await waitFor(() => expect(api.POST).toHaveBeenCalledOnce());
    const pending = Promise.withResolvers<{ data: { url: string }; response: Response }>();
    api.POST.mockReturnValueOnce(pending.promise);
    const download = screen.getByRole("button", { name: 'Ladda ner original "intervju.mp3"' });
    download.focus();
    fireEvent.click(download);
    await waitFor(() => expect(download.getAttribute("aria-busy")).toBe("true"));
    expect(download.hasAttribute("disabled")).toBe(false);
    expect(document.activeElement).toBe(download);
    fireEvent.click(download);
    expect(api.POST).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole("tab", { name: "Resultat" }));
    pending.resolve({
      data: { url: "http://backend:8000/api/v1/files/file-1/original/download/?token=late" },
      response: new Response()
    });
    await waitFor(() => expect(screen.getByRole("tabpanel", { name: "Resultat" })).toBeTruthy());
    await waitFor(() => expect(click).toHaveBeenCalledOnce());
    expect((click.mock.contexts[0] as HTMLAnchorElement).getAttribute("href")).toContain(
      "/original/download/?token=late"
    );
    expect(toast.error).not.toHaveBeenCalled();
  });

  it.each([
    ["in progress", "Pågår"],
    ["queued", "I kö"]
  ] as const)(
    "shows a %s run as pending: its status, a skeleton and where the result is kept",
    async (status, label) => {
      const { container } = renderResult(
        makeRun({ status, output: null, finished_at: null } as Partial<AppRun>)
      );

      // A static Token, not a live region of its own.
      expect(screen.getByText(label)).toBeTruthy();
      expect(screen.queryByRole("status", { name: label })).toBeNull();
      expect(screen.getByText("Ditt resultat genereras.")).toBeTruthy();
      expect(screen.getByText("Du kan lämna sidan, resultatet sparas i Resultat.")).toBeTruthy();
      expect(container.querySelector("[data-result-skeleton]")?.getAttribute("aria-hidden")).toBe(
        "true"
      );
      // Nothing to copy or download yet: only Ny körning is docked.
      expect(dockedActions()).toEqual(["Ny körning"]);
      await expectNoAxeViolations(container);
    }
  );

  it("docks only Ny körning for a failed run without output", () => {
    renderResult(makeRun({ status: "failed", output: null, input: { text: "x", files: [] } }));

    expect(screen.getByText("Misslyckades")).toBeTruthy();
    expect(dockedActions()).toEqual(["Ny körning"]);
  });

  it("downloads failed-run input files through the app's authenticated proxy", async () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const run = makeRun({ status: "failed", output: null });
    run.input.files[0]!.transcription = null;
    renderResult(run);
    fireEvent.click(screen.getByRole("button", { name: 'Ladda ner "intervju.mp3"' }));
    await waitFor(() => expect(click).toHaveBeenCalledTimes(1));
    const anchor = click.mock.contexts[0] as HTMLAnchorElement;
    expect(anchor.getAttribute("href")).toBe(
      `${API_BASE}/api/v1/files/file-1/download/?token=signed-value`
    );
    expect(anchor.download).toBe("intervju.mp3");
    expect(open).not.toHaveBeenCalled();
  });

  it("says why a failed-run download could not be signed, with its trace id", async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    api.POST.mockResolvedValueOnce({
      data: undefined as never,
      error: { message: "Filen finns inte längre" },
      response: new Response("{}", { status: 404, headers: { "x-trace-id": "trace-9" } })
    } as never);
    const run = makeRun({ status: "failed", output: null });
    run.input.files[0]!.transcription = null;
    renderResult(run);
    fireEvent.click(screen.getByRole("button", { name: 'Ladda ner "intervju.mp3"' }));
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Filen finns inte längre",
        expect.objectContaining({ description: expect.stringContaining("trace-9") })
      )
    );
    expect(click).not.toHaveBeenCalled();
  });
});
