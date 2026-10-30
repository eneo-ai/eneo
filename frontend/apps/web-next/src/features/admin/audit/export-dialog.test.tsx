// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EneoApiError } from "@/lib/api/errors";
import { renderInApp } from "@/test/render";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
const save = vi.hoisted(() => vi.fn());
vi.mock("@/features/files/signed-file-url", () => ({ saveUrl: save }));

import { ExportDialog } from "./export-dialog";

async function flush(ms = 20) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  api.GET.mockReset();
  api.POST.mockReset();
  save.mockReset();
});

describe("ExportDialog", () => {
  it("rechecks the bound session and gets a fresh signed URL when download is requested", async () => {
    api.POST.mockResolvedValue({ data: { job_id: "job-1" }, response: new Response("{}") });
    const completed = { job_id: "job-1", status: "completed", progress: 100 };
    api.GET.mockResolvedValueOnce({
      data: {
        ...completed,
        download_url: "/api/v1/audit/logs/export/job-1/signed-download?token=old"
      },
      response: new Response("{}")
    });
    renderInApp(
      <ExportDialog open onOpenChange={() => {}} filters={{ page: 1, actions: [], search: "" }} />
    );
    fireEvent.click(screen.getByRole("button", { name: "Exportera" }));
    await flush();
    api.GET.mockResolvedValueOnce({
      data: {
        ...completed,
        download_url: "/api/v1/audit/logs/export/job-1/signed-download?token=fresh"
      },
      response: new Response("{}")
    });
    fireEvent.click(screen.getByRole("button", { name: "Ladda ner" }));
    await flush();
    expect(api.GET).toHaveBeenCalledTimes(2);
    expect(save).toHaveBeenCalledExactlyOnceWith(
      "/api/eneo/api/v1/audit/logs/export/job-1/signed-download?token=fresh",
      ""
    );
    api.GET.mockRejectedValueOnce(new EneoApiError("Session changed", { status: 401, code: 9090 }));
    fireEvent.click(screen.getByRole("button", { name: "Ladda ner" }));
    await flush();
    expect(save).toHaveBeenCalledTimes(1);
  });
  it("stops polling an export job whose status is gone", async () => {
    api.POST.mockResolvedValue({ data: { job_id: "job-1" }, response: new Response("{}") });
    api.GET.mockResolvedValueOnce({
      data: { job_id: "job-1", status: "processing", progress: 40 },
      response: new Response("{}")
    }).mockRejectedValue(new EneoApiError("Not found", { status: 404 }));

    renderInApp(
      <ExportDialog open onOpenChange={() => {}} filters={{ page: 1, actions: [], search: "" }} />
    );
    fireEvent.click(screen.getByRole("button", { name: "Exportera" }));
    await flush();
    expect(api.GET).toHaveBeenCalledTimes(1);

    // The next poll finds the job expired; the dialog says so and asks no more.
    await flush(2_000);
    expect(api.GET).toHaveBeenCalledTimes(2);
    expect(screen.getByText(/Exporten har gått ut/, { selector: "p" })).toBeTruthy();

    await flush(10_000);
    expect(api.GET).toHaveBeenCalledTimes(2);
  });
});
