import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { invalidateAfterJobs } from "./job-invalidation";

describe("invalidateAfterJobs", () => {
  it("refreshes an open app run, so its result page leaves its pending state", () => {
    // The result page stops polling while the job feed is connected: the
    // finished job is all that tells it the run is done.
    const queryClient = new QueryClient();
    queryClient.setQueryData(["app-runs", "run-1"], { status: "in progress" });
    queryClient.setQueryData(["apps", "app-1", "runs"], []);

    invalidateAfterJobs(queryClient);

    expect(queryClient.getQueryState(["app-runs", "run-1"])?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(["apps", "app-1", "runs"])?.isInvalidated).toBe(true);
  });

  it("leaves a run's signed audio links alone, so a playing transcription keeps playing", () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(["app-run-audio-urls", "run-1"], { "file-1": "signed" });

    invalidateAfterJobs(queryClient);

    expect(queryClient.getQueryState(["app-run-audio-urls", "run-1"])?.isInvalidated).toBe(false);
  });
});
