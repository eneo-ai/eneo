// @vitest-environment jsdom
import { Dialog } from "@astryxdesign/core/Dialog";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { JobIndicator } from "./job-indicator";
import type { Job, Upload } from "./use-jobs";

const jobs = vi.hoisted(() => ({
  state: { jobs: [] as Job[], uploads: [] as Upload[], runningCount: 0 }
}));

vi.mock("./use-jobs", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./use-jobs")>()),
  useJobActivity: () => jobs.state
}));

afterEach(() => {
  cleanup();
  jobs.state = { jobs: [], uploads: [], runningCount: 0 };
});

const job = (overrides: Partial<Job>) =>
  ({
    id: "job-1",
    name: "Avtal.pdf",
    task: "upload_info_blob",
    status: "complete",
    result_location: null,
    ...overrides
  }) as Job;

describe("JobIndicator", () => {
  it("opens its panel from the bell and closes it with Escape, back on the bell", async () => {
    renderInApp(<JobIndicator />);
    const bell = screen.getByRole("button", { name: "Aviseringar" });
    bell.focus();
    fireEvent.click(bell);

    const panel = await screen.findByRole("dialog", { name: "Aviseringar och jobb" });
    expect(bell.getAttribute("aria-expanded")).toBe("true");
    expect(within(panel).getByText("Allt är uppdaterat")).toBeTruthy();
    await expectNoAxeViolations(document.body);

    fireEvent.keyDown(panel, { key: "Escape" });
    await waitFor(() => expect(bell.getAttribute("aria-expanded")).toBe("false"));
    expect(document.activeElement).toBe(bell);
  });

  it("says how many jobs run and lists uploads, jobs and failures", async () => {
    jobs.state = {
      runningCount: 2,
      uploads: [
        {
          id: "u1",
          file: new File(["x"], "Protokoll.docx"),
          status: "uploading",
          collectionId: "c1",
          progress: 40
        }
      ],
      jobs: [
        job({ id: "j1", name: "Riktlinjer.pdf", status: "in progress" }),
        job({
          id: "j2",
          name: "Trasig.pdf",
          status: "failed",
          failure_code: "encrypted",
          result_location: "PDF is encrypted: worker trace"
        })
      ]
    };
    renderInApp(<JobIndicator />);
    fireEvent.click(screen.getByRole("button", { name: "Aviseringar, 2 pågår" }));
    const panel = await screen.findByRole("dialog", { name: "Aviseringar och jobb" });

    expect(within(panel).getByRole("progressbar", { name: "Protokoll.docx" })).toBeTruthy();
    expect(within(panel).getByText("Riktlinjer.pdf")).toBeTruthy();
    const failure = within(panel).getByRole("button", { name: /Trasig\.pdf/ });
    expect(failure.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(failure);
    expect(failure.getAttribute("aria-expanded")).toBe("true");
    // The typed code's guidance, never the worker's own text.
    expect(within(panel).getByText(/lösenordsskyddad/)).toBeTruthy();
    expect(within(panel).queryByText(/worker trace/)).toBeNull();
    await expectNoAxeViolations(document.body);
  });

  it("shows the localized typed reason for an unreachable crawl", async () => {
    jobs.state = {
      runningCount: 0,
      uploads: [],
      jobs: [
        job({
          name: "offline.example",
          task: "crawl",
          status: "failed",
          failure_code: "remote_unreachable",
          result_location: "The crawl exceeded its configured time limit"
        })
      ]
    };
    renderInApp(<JobIndicator />);
    fireEvent.click(screen.getByRole("button", { name: "Aviseringar" }));
    const panel = await screen.findByRole("dialog", { name: "Aviseringar och jobb" });
    fireEvent.click(within(panel).getByRole("button", { name: /offline\.example/ }));

    expect(within(panel).getByText("Misslyckades")).toBeTruthy();
    expect(within(panel).getByText(/Webbplatsen kunde inte nås/)).toBeTruthy();
    expect(within(panel).queryByText(/configured time limit/)).toBeNull();
  });

  it("presents an intentional crawl cancellation as stopped instead of failed", async () => {
    jobs.state = {
      runningCount: 0,
      uploads: [],
      jobs: [
        job({
          name: "intranet.example",
          task: "crawl",
          status: "failed",
          failure_code: "cancelled",
          result_location: "The crawl was stopped by a user"
        })
      ]
    };
    renderInApp(<JobIndicator />);
    fireEvent.click(screen.getByRole("button", { name: "Aviseringar" }));
    const panel = await screen.findByRole("dialog", { name: "Aviseringar och jobb" });

    expect(within(panel).getByText("Stoppad")).toBeTruthy();
    expect(within(panel).queryByText("Misslyckades")).toBeNull();
    expect(within(panel).queryByRole("button", { name: /intranet\.example/ })).toBeNull();
  });

  it("shows the reason when a crawl completes with partial results", async () => {
    jobs.state = {
      runningCount: 0,
      uploads: [],
      jobs: [
        job({
          name: "partial.example",
          task: "crawl",
          status: "complete",
          failure_code: "remote_unreachable"
        })
      ]
    };
    renderInApp(<JobIndicator />);
    fireEvent.click(screen.getByRole("button", { name: "Aviseringar" }));
    const panel = await screen.findByRole("dialog", { name: "Aviseringar och jobb" });
    fireEvent.click(within(panel).getByRole("button", { name: /partial\.example/ }));

    expect(within(panel).getByText("Delvis klar")).toBeTruthy();
    expect(within(panel).getByText(/Webbplatsen kunde inte nås/)).toBeTruthy();
    expect(within(panel).queryByText("Klar")).toBeNull();
    await expectNoAxeViolations(document.body);
  });

  it("shows active jobs whose task has no dedicated section", async () => {
    jobs.state = {
      runningCount: 1,
      uploads: [],
      jobs: [job({ task: "run_app", name: "Veckorapport", status: "in progress" })]
    };
    renderInApp(<JobIndicator />);
    fireEvent.click(screen.getByRole("button", { name: "Aviseringar, 1 pågår" }));
    const panel = await screen.findByRole("dialog", { name: "Aviseringar och jobb" });

    expect(within(panel).getByText("Aktivitet")).toBeTruthy();
    expect(within(panel).getByText("Veckorapport")).toBeTruthy();
    expect(within(panel).queryByText("Allt är uppdaterat")).toBeNull();
  });

  it("shows long names in full instead of cutting them off behind a tooltip", async () => {
    const long = "Protokoll_kommunstyrelsen_2026-09-21_bilaga_4_slutlig_version.pdf";
    jobs.state = {
      runningCount: 1,
      uploads: [
        {
          id: "u1",
          file: new File(["x"], long),
          status: "queued",
          collectionId: "c1",
          progress: 0
        }
      ],
      jobs: [job({ id: "j1", name: long, status: "failed", result_location: "Tom fil" })]
    };
    renderInApp(<JobIndicator />);
    fireEvent.click(screen.getByRole("button", { name: "Aviseringar, 1 pågår" }));
    const panel = await screen.findByRole("dialog", { name: "Aviseringar och jobb" });

    const names = within(panel).getAllByText(long);
    expect(names).toHaveLength(2);
    for (const name of names) {
      // Not reachable by keyboard or touch: truncation with a title tooltip.
      expect(name.className).not.toMatch(/truncate/);
      expect(name.className).toContain("wrap-anywhere");
    }
    expect(panel.querySelector("[title]")).toBeNull();
  });

  it("opens inside a modal dialog such as the navigation drawer", async () => {
    renderInApp(
      <Dialog isOpen onOpenChange={() => {}} aria-label="Meny">
        <JobIndicator />
      </Dialog>
    );
    const drawer = await screen.findByRole("dialog", { name: "Meny" });
    fireEvent.click(within(drawer).getByRole("button", { name: "Aviseringar" }));

    // Rendered next to its trigger (in the top layer), not in <body> behind
    // the modal like the old Radix popover.
    const panel = await screen.findByRole("dialog", { name: "Aviseringar och jobb" });
    expect(drawer.contains(panel)).toBe(true);
  });
});
