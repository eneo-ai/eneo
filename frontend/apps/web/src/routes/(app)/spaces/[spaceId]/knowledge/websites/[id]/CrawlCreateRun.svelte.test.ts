import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CrawlRun, Website } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";

const createRun = vi.hoisted(() => vi.fn());
const cancelRun = vi.hoisted(() => vi.fn());
const invalidate = vi.hoisted(() => vi.fn(async () => {}));
const toastError = vi.hoisted(() => vi.fn());

vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    websites: {
      crawlRuns: {
        create: createRun,
        cancel: cancelRun
      }
    }
  })
}));

vi.mock("$app/navigation", () => ({ invalidate }));

vi.mock("$lib/core/errors", () => ({ toastError }));

import CrawlCreateRun from "./CrawlCreateRun.svelte";

const website = {
  id: crypto.randomUUID(),
  name: "Sundsvall",
  url: "https://sundsvall.se"
} as Website;

function activeRun(overrides: Partial<CrawlRun> = {}): CrawlRun {
  return {
    id: crypto.randomUUID(),
    pages_crawled: null,
    files_downloaded: null,
    pages_failed: null,
    files_failed: null,
    status: "in progress",
    phase: "running",
    outcome: null,
    origin: "manual",
    result_location: null,
    finished_at: null,
    failure_code: null,
    failure_detail: null,
    cancel_requested_at: null,
    attempt_count: 1,
    ...overrides
  };
}

describe("CrawlCreateRun", () => {
  beforeEach(() => {
    createRun.mockReset().mockResolvedValue(activeRun({ phase: "queued", status: "queued" }));
    cancelRun.mockReset().mockResolvedValue(
      activeRun({
        phase: "terminal",
        outcome: "cancelled",
        status: "failed",
        failure_code: "cancelled"
      })
    );
    invalidate.mockClear();
    toastError.mockClear();
  });

  it("confirms and stops an active crawl, then allows a rerun", async () => {
    const run = activeRun();
    const rendered = render(CrawlCreateRun, { website, activeRun: run, hasHistory: true });

    await page.getByRole("button", { name: m.stop_crawl(), exact: true }).click();
    const dialog = page.getByRole("alertdialog");
    await expect.element(dialog.getByText(m.stop_crawl_title(), { exact: true })).toBeVisible();

    await dialog.getByRole("button", { name: m.stop_crawl(), exact: true }).click();

    expect(cancelRun).toHaveBeenCalledWith(run);
    expect(invalidate).toHaveBeenCalledWith("crawlruns:list");

    await rendered.rerender({ website, activeRun: undefined, hasHistory: true });
    await expect
      .element(page.getByRole("button", { name: m.run_crawl_again(), exact: true }))
      .toBeVisible();
  });

  it("does not offer another stop after a stop has already been requested", async () => {
    render(CrawlCreateRun, {
      website,
      activeRun: activeRun({ phase: "stopping", cancel_requested_at: new Date().toISOString() }),
      hasHistory: true
    });

    const button = page.getByRole("button", { name: m.stopping_crawl(), exact: true });
    await expect.element(button).toBeDisabled();
  });

  it("restores the start action after the API rejects a rerun", async () => {
    createRun.mockRejectedValueOnce(new Error("queue unavailable"));
    render(CrawlCreateRun, { website, activeRun: undefined, hasHistory: true });

    await page.getByRole("button", { name: m.run_crawl_again(), exact: true }).click();
    const dialog = page.getByRole("alertdialog");
    await dialog.getByRole("button", { name: m.start_crawl(), exact: true }).click();

    expect(toastError).toHaveBeenCalledOnce();
    await expect
      .element(dialog.getByRole("button", { name: m.start_crawl(), exact: true }))
      .toBeEnabled();
  });
});
