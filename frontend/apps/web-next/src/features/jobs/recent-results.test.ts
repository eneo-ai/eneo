// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Job } from "./jobs";
import { recordFinishedJob, resetRecentResults, useRecentInfoBlobIds } from "./recent-results";

const upload = (id: string): Job =>
  ({
    id: `job-${id}`,
    task: "upload_info_blob",
    status: "complete",
    result_location: `/api/v1/info-blobs/${id}/`
  }) as Job;
const BLOB = "5d1b9c1e-0b4e-4c21-9d7c-2f0f0a6d3e11";

afterEach(() => {
  resetRecentResults();
  vi.useRealTimers();
});

describe("recent results", () => {
  it("exposes the info-blob of a finished upload, then forgets it", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useRecentInfoBlobIds());
    expect(result.current.has(BLOB)).toBe(false);

    act(() => recordFinishedJob(upload(BLOB)));
    expect(result.current.has(BLOB)).toBe(true);

    act(() => vi.advanceTimersByTime(8_000));
    expect(result.current.has(BLOB)).toBe(false);
  });

  it("ignores jobs without an info-blob result", () => {
    const { result } = renderHook(() => useRecentInfoBlobIds());
    act(() =>
      recordFinishedJob({
        id: "c",
        task: "crawl",
        status: "complete",
        result_location: null
      } as Job)
    );
    expect(result.current.size).toBe(0);
  });
});
