// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { API_BASE } from "@/lib/api/base";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testQueryClient } from "@/test/render";
import type { AppRun } from "../apps";

const api = vi.hoisted(() => ({
  POST: vi.fn(async () => ({
    data: { url: "http://backend:8000/api/v1/files/file-1/download/?token=signed-value" },
    response: new Response("{}")
  }))
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
const toast = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn() }));
vi.mock("@/lib/toast", () => ({ toast }));

import { ResultDetail } from "./result-detail";

afterEach(() => {
  cleanup();
  api.POST.mockClear();
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
          transcription: "Hej och välkommen till intervjun."
        }
      ]
    },
    ...overrides
  } as AppRun;
}

function renderResult(run: AppRun) {
  const queryClient = testQueryClient();
  queryClient.setQueryData(["app-runs", run.id], run);
  return renderInApp(<ResultDetail runId={run.id} backHref="/apps" newRunHref="/apps/new" />, {
    queryClient
  });
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

    fireEvent.keyDown(transcription, { key: "Home" });
    expect(document.activeElement).toBe(results);
  });

  it("shows the output without tabs when nothing was transcribed", () => {
    renderResult(makeRun({ input: { text: "Vad säger avtalet?", files: [] } } as Partial<AppRun>));

    expect(screen.queryByRole("tablist")).toBeNull();
    expect(screen.getByText("Sammanfattning av intervjun")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Kopiera" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Ny körning" }).getAttribute("href")).toBe("/apps/new");
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
