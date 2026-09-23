import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { FlowRunResultFile } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";

import FlowRunEvidenceSummary from "./FlowRunEvidenceSummary.svelte";

const traceId = "4f9b5ca1-aeb8-40c5-8187-67efe518c9e9";

function renderWithTrace() {
  render(FlowRunEvidenceSummary, { props: { runStatus: "completed", traceId } });
  return screen.getByRole("button", { name: m.flow_run_evidence_trace_id_copy() });
}

describe("FlowRunEvidenceSummary trace identifier", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("copies the whole identifier, not the shortened badge text", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });

    const button = renderWithTrace();
    expect(button.textContent).not.toContain(traceId);
    await fireEvent.click(button);

    expect(writeText).toHaveBeenCalledWith(traceId);
  });

  it("announces the confirmation instead of only changing the badge", async () => {
    vi.stubGlobal("navigator", {
      ...navigator,
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) }
    });

    await fireEvent.click(renderWithTrace());

    await waitFor(() =>
      expect(screen.getByRole("status").textContent?.trim()).toBe(
        m.flow_run_evidence_trace_id_copied()
      )
    );
  });

  it("claims nothing when the clipboard refuses", async () => {
    vi.stubGlobal("navigator", {
      ...navigator,
      clipboard: { writeText: vi.fn().mockRejectedValue(new Error("denied")) }
    });
    vi.spyOn(console, "error").mockImplementation(() => {});

    await fireEvent.click(renderWithTrace());

    await waitFor(() => expect(screen.getByRole("status").textContent?.trim()).toBe(""));
  });
});

describe("FlowRunEvidenceSummary result files", () => {
  afterEach(() => cleanup());

  it("offers every file the run created without opening a step", async () => {
    const onDownloadResultFile = vi.fn();
    const file = {
      file_id: "file-1",
      name: "Genomförandeplan.pdf",
      availability: "available"
    } as FlowRunResultFile;
    render(FlowRunEvidenceSummary, {
      props: { runStatus: "completed", resultFiles: [file], onDownloadResultFile }
    });

    expect(screen.getByText(m.flow_run_result_files_title())).toBeTruthy();
    await fireEvent.click(
      screen.getByRole("button", {
        name: m.flow_run_download_artifact({ name: "Genomförandeplan.pdf" })
      })
    );
    expect(onDownloadResultFile).toHaveBeenCalledWith("file-1");
  });
});
