// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testQueryClient } from "@/test/render";
import type { AppRun } from "../apps";

const api = vi.hoisted(() => ({
  POST: vi.fn(async () => ({
    data: { url: "https://files.example/intervju.mp3" },
    response: new Response("{}")
  }))
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { ResultDetail } from "./result-detail";

afterEach(() => {
  cleanup();
  api.POST.mockClear();
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
        "https://files.example/intervju.mp3"
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
});
