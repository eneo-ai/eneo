// @vitest-environment jsdom
import { waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { type Job, JobsProvider, useJobs } from "./use-jobs";

const job = { id: "job-1", name: "Avtal.pdf", status: "in progress" } as Job;

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: vi.fn(async () => ({ data: { items: [job] }, response: new Response("{}") }))
  }
}));

it("keeps its context still when the jobs arrive", async () => {
  // The provider sits above every page: a context that changes while React
  // still hydrates a page makes React render the page again from scratch.
  const seen: ReturnType<typeof useJobs>[] = [];
  function Consumer() {
    seen.push(useJobs());
    return null;
  }

  const { queryClient } = renderInApp(
    <JobsProvider>
      <Consumer />
    </JobsProvider>
  );

  await waitFor(() => expect(queryClient.getQueryData(["jobs"])).toEqual([job]));
  expect(new Set(seen).size).toBe(1);
});
