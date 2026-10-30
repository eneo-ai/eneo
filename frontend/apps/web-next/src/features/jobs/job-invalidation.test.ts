import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { invalidateAfterJobs } from "./job-invalidation";
import { browserApi } from "@/lib/api/browser";
import { storageQueryOptions, storageSpacesQueryOptions } from "@/features/admin/usage/usage";

describe("invalidateAfterJobs", () => {
  it("refreshes storage totals and the space breakdown after an indexing job finishes", () => {
    const queryClient = new QueryClient();
    const storage = storageQueryOptions(browserApi);
    queryClient.setQueryData(storage.queryKey, {
      total_used: 600,
      personal_used: 200,
      shared_used: 400,
      limit: 1000
    });

    const spaces = storageSpacesQueryOptions(browserApi);
    queryClient.setQueryData(spaces.queryKey, { items: [] });

    invalidateAfterJobs(queryClient);

    expect(queryClient.getQueryState(spaces.queryKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(storage.queryKey)?.isInvalidated).toBe(true);
  });

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
