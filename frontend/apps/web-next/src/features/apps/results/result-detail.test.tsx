// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
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

import { ResultDetail } from "./result-detail";

afterEach(() => {
  cleanup();
  api.POST.mockClear();
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

/** The docked bar's controls, in the order they sit. */
function dockedActions() {
  const dock = screen.getByRole("group", { name: "Resultat, åtgärder" });
  return [...dock.querySelectorAll("a, button")].map((control) => control.textContent);
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
        "/api/eneo/api/v1/files/file-1/download/?token=signed-value"
      )
    );
    await expectNoAxeViolations(container);

    // The page's Kopiera and Ladda ner act on the output, so they leave with
    // it: the transcription has its own Ladda ner per file.
    expect(dockedActions()).toEqual(["Ny körning"]);

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

  it("docks Kopiera, Ladda ner and Ny körning, the primary last, for a finished run", () => {
    const { container } = renderResult(makeRun());

    expect(dockedActions()).toEqual(["Kopiera", "Ladda ner", "Ny körning"]);
    // The input files are one line of the summary.
    expect(container.querySelector("aside")?.textContent).toContain("Indataintervju.mp3");
    // The output panel no longer repeats them.
    const panel = screen.getByRole("tabpanel", { name: "Resultat" });
    expect(within(panel).queryByRole("button", { name: "Kopiera" })).toBeNull();
    expect(screen.getByText("Slutförd")).toBeTruthy();
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
    const run = makeRun({ status: "failed", output: null });
    run.input.files[0]!.transcription = null;
    renderResult(run);
    fireEvent.click(screen.getByRole("button", { name: 'Ladda ner "intervju.mp3"' }));
    await waitFor(() =>
      expect(open).toHaveBeenCalledWith(
        "/api/eneo/api/v1/files/file-1/download/?token=signed-value",
        "_blank"
      )
    );
  });
});
