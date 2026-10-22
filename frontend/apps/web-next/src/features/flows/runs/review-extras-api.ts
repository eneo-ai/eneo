import { infiniteQueryOptions } from "@tanstack/react-query";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { runKeys, type ReviewCheckpoint } from "./runs-api";

/**
 * The review endpoints beyond deciding in one step: approving without
 * letting the run go on (the run then waits to be resumed), and the
 * checkpoint's edit history, page by page.
 */

export type ReviewEditPage = Schema<"FlowRunReviewCheckpointEditPagePublic">;
export type ReviewEdit = Schema<"FlowRunReviewCheckpointEditPublic">;

type CheckpointRef = Pick<ReviewCheckpoint, "flow_id" | "flow_run_id" | "id" | "revision">;

/** Approves the output as it stands; the run goes on only when someone resumes it. */
export function approveOnly(checkpoint: CheckpointRef): Promise<ReviewCheckpoint> {
  return unwrap(
    browserApi.POST(
      "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/approve/",
      {
        params: {
          path: {
            id: checkpoint.flow_id,
            run_id: checkpoint.flow_run_id,
            checkpoint_id: checkpoint.id
          }
        },
        body: { expected_checkpoint_revision: checkpoint.revision }
      }
    )
  );
}

/** Edits per page of the history. */
export const REVIEW_EDITS_PAGE_SIZE = 20;

/**
 * The checkpoint's edits in the order they happened, read for the revision
 * the panel shows; each page is an audited read, made when asked for.
 */
export function reviewEditsQueryOptions(checkpoint: CheckpointRef) {
  return infiniteQueryOptions({
    queryKey: [
      ...runKeys.run(checkpoint.flow_id, checkpoint.flow_run_id),
      "review-edits",
      checkpoint.id,
      checkpoint.revision
    ],
    queryFn: ({ pageParam, signal }): Promise<ReviewEditPage> =>
      unwrap(
        browserApi.GET(
          "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/edits",
          {
            params: {
              path: {
                id: checkpoint.flow_id,
                run_id: checkpoint.flow_run_id,
                checkpoint_id: checkpoint.id
              },
              query: {
                limit: REVIEW_EDITS_PAGE_SIZE,
                ...(pageParam === null ? {} : { after_revision: pageParam })
              }
            },
            signal
          }
        )
      ),
    initialPageParam: null as number | null,
    getNextPageParam: (last) =>
      last.truncated && last.next_after_revision !== null ? last.next_after_revision : undefined
  });
}
