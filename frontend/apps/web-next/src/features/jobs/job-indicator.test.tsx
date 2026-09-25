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
  useJobs: () => jobs.state
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
        job({ id: "j2", name: "Trasig.pdf", status: "failed", result_location: "Tom fil" })
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
    expect(within(panel).getByText("Tom fil")).toBeTruthy();
    await expectNoAxeViolations(document.body);
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
