import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";
import { browserApi, type EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { proxiedDownloadPath } from "@/features/files/signed-file-url";
import { OMISSION_REASON, type TranscriptSourceSegment } from "./transcript";

/**
 * The flow-core run endpoints the run screens use: the run contract, uploads,
 * starting, listing and following runs, their audited detail and steps,
 * cancel, retry and redispatch, downloads and human review.
 *
 * Content-free reads (the list, `/status/`, the run-pinned graph) are what
 * polling uses. The run detail and its steps are audited content reads: they
 * are read when the screen opens and again only when the run moved on.
 */

export type RunContract = Schema<"FlowRunContractPublic">;
export type RunFormField = Schema<"FormFieldPublic">;
export type RuntimeInput = Schema<"FlowRuntimeInputContractPublic">;
export type RunCreateRequest = Schema<"FlowRunCreateRequest">;
export type RunSummary = Schema<"FlowRunSummaryPublic">;
export type RunPublic = Schema<"FlowRunPublic">;
export type RunDetail = Schema<"FlowRunDetailPublic">;
export type RunStatus = Schema<"FlowRunStatus">;
export type RunError = Schema<"FlowRunError">;
export type RunStep = Schema<"FlowRunStepPublic">;
export type RunStepStatus = Schema<"FlowStepResultStatus">;
export type RunResultFile = Schema<"FlowRunStepResultFile">;
export type RunGraph = Schema<"GraphResponse">;
export type RunGraphNode = Schema<"GraphNode">;
export type RunRetry = Schema<"FlowRunRetryPublic">;
export type RunRedispatch = Schema<"FlowRunRedispatchResponse">;
export type UploadedFile = Schema<"FilePublic">;
export type ReviewCheckpoint = Schema<"FlowRunReviewCheckpointPublic">;
export type ReviewResume = Schema<"FlowRunReviewCheckpointResumeResponse">;
export type RunEvidence = Schema<"FlowRunEvidenceResponse">;
export type TokenUsage = Schema<"FlowRunTokenUsagePublic">;
export type TranscriptionUsage = Schema<"FlowRunTranscriptionUsagePublic">;

/** Every run query of a flow sits under `["flows", flowId, "runs"]`. */
export const runKeys = {
  all: (flowId: string) => ["flows", flowId, "runs"] as const,
  contract: (flowId: string) => ["flows", flowId, "runs", "contract"] as const,
  list: (flowId: string) => ["flows", flowId, "runs", "list"] as const,
  listOf: (flowId: string, filter: RunsFilter) =>
    ["flows", flowId, "runs", "list", filter] as const,
  run: (flowId: string, runId: string) => ["flows", flowId, "runs", runId] as const,
  progress: (flowId: string, runId: string) =>
    ["flows", flowId, "runs", runId, "progress"] as const,
  /** `version`: what the content-free reads said about the run when this was read. */
  detail: (flowId: string, runId: string, version: string) =>
    ["flows", flowId, "runs", runId, "detail", version] as const,
  steps: (flowId: string, runId: string, version: string) =>
    ["flows", flowId, "runs", runId, "steps", version] as const,
  review: (flowId: string, runId: string, version: string) =>
    ["flows", flowId, "runs", runId, "review", version] as const,
  evidence: (flowId: string, runId: string) => ["flows", flowId, "runs", runId, "evidence"] as const
};

/** The published contract a run form is built from; a draft has none (404 or 400). */
export function runContractQueryOptions(flowId: string) {
  return queryOptions({
    queryKey: runKeys.contract(flowId),
    queryFn: ({ signal }): Promise<RunContract> =>
      unwrap(
        browserApi.GET("/api/v1/flows/{id}/run-contract/", {
          params: { path: { id: flowId } },
          signal
        })
      ),
    // A republish changes it; the form reads it fresh each time it opens.
    staleTime: 0
  });
}

/** Runs per page of the history. */
export const RUNS_PAGE_SIZE = 25;
/** The history reads at most this many pages, newest first. */
export const RUNS_MAX_PAGES = 8;

/**
 * `mine`: only the runs the caller started, within those the caller may see.
 * `status`: only runs with this status; the list endpoint filters, so every
 * page and "show more" stay within it.
 */
export type RunsFilter = { mine: boolean; status?: RunStatus | null };

export function runsListQueryOptions(flowId: string, filter: RunsFilter = { mine: false }) {
  return infiniteQueryOptions({
    queryKey: runKeys.listOf(flowId, filter),
    queryFn: ({ pageParam, signal }) =>
      unwrap(
        browserApi.GET("/api/v1/flows/{id}/runs/", {
          params: {
            path: { id: flowId },
            query: {
              limit: RUNS_PAGE_SIZE,
              offset: pageParam * RUNS_PAGE_SIZE,
              ...(filter.mine ? { mine: true } : {}),
              ...(filter.status ? { status: [filter.status] } : {})
            }
          },
          signal
        })
      ),
    initialPageParam: 0,
    getNextPageParam: (last, pages) =>
      last.has_more && pages.length < RUNS_MAX_PAGES ? pages.length : undefined
  });
}

/**
 * The run's audited detail, read once per `version` of the run (see
 * `progressSignature`): a run that has not moved is not read again.
 */
export function runDetailQueryOptions(
  api: EneoClient,
  flowId: string,
  runId: string,
  version: string
) {
  return queryOptions({
    queryKey: runKeys.detail(flowId, runId, version),
    queryFn: ({ signal }): Promise<RunDetail> =>
      unwrap(
        api.GET("/api/v1/flows/{id}/runs/{run_id}/", {
          params: { path: { id: flowId, run_id: runId } },
          signal
        })
      )
  });
}

export function runStepsQueryOptions(flowId: string, runId: string, version: string) {
  return queryOptions({
    queryKey: runKeys.steps(flowId, runId, version),
    queryFn: ({ signal }): Promise<RunStep[]> =>
      unwrap(
        browserApi.GET("/api/v1/flows/{id}/runs/{run_id}/steps/", {
          params: { path: { id: flowId, run_id: runId } },
          signal
        })
      )
  });
}

export function getRunStatus(flowId: string, runId: string, signal?: AbortSignal) {
  return unwrap(
    browserApi.GET("/api/v1/flows/{id}/runs/{run_id}/status/", {
      params: { path: { id: flowId, run_id: runId } },
      signal
    })
  );
}

/** The run's own version of the flow, with each step's status in this run. */
export function getRunGraph(flowId: string, runId: string, signal?: AbortSignal) {
  return unwrap(
    browserApi.GET("/api/v1/flows/{id}/graph/", {
      params: { path: { id: flowId }, query: { run_id: runId } },
      signal
    })
  );
}

export function runEvidenceQueryOptions(flowId: string, runId: string) {
  return queryOptions({
    queryKey: runKeys.evidence(flowId, runId),
    queryFn: ({ signal }): Promise<RunEvidence> =>
      unwrap(
        browserApi.GET("/api/v1/flows/{id}/runs/{run_id}/evidence/", {
          params: { path: { id: flowId, run_id: runId } },
          signal
        })
      )
  });
}

export function startRun(
  flowId: string,
  body: RunCreateRequest,
  idempotencyKey: string
): Promise<RunPublic> {
  return unwrap(
    browserApi.POST("/api/v1/flows/{id}/runs/", {
      params: { path: { id: flowId }, header: { "Idempotency-Key": idempotencyKey } },
      body
    })
  );
}

/** Removes an upload that never became part of a run. */
export function deleteRuntimeFile(flowId: string, fileId: string): Promise<unknown> {
  return unwrap(
    browserApi.DELETE("/api/v1/flows/{id}/runtime-files/{file_id}/", {
      params: { path: { id: flowId, file_id: fileId } }
    })
  );
}

export function cancelRun(flowId: string, runId: string): Promise<RunPublic> {
  return unwrap(
    browserApi.POST("/api/v1/flows/{id}/runs/{run_id}/cancel/", {
      params: { path: { id: flowId, run_id: runId } }
    })
  );
}

export function retryRun(flowId: string, runId: string, idempotencyKey: string): Promise<RunRetry> {
  return unwrap(
    browserApi.POST("/api/v1/flows/{id}/runs/{run_id}/retry/", {
      params: {
        path: { id: flowId, run_id: runId },
        header: { "Idempotency-Key": idempotencyKey }
      }
    })
  );
}

export function redispatchRun(
  flowId: string,
  run: Pick<RunSummary, "id" | "dispatch_exhausted_at">
): Promise<RunRedispatch> {
  return unwrap(
    browserApi.POST("/api/v1/flows/{id}/runs/{run_id}/redispatch/", {
      params: { path: { id: flowId, run_id: run.id } },
      body: run.dispatch_exhausted_at
        ? { expected_dispatch_exhausted_at: run.dispatch_exhausted_at }
        : {}
    })
  );
}

/** A short-lived download path (through the app's proxy) for a file a run produced. */
export async function artifactDownloadPath(
  flowId: string,
  runId: string,
  fileId: string
): Promise<string> {
  const signed = await unwrap(
    browserApi.POST("/api/v1/flows/{id}/runs/{run_id}/artifacts/{file_id}/signed-url/", {
      params: { path: { id: flowId, run_id: runId, file_id: fileId } },
      body: { content_disposition: "attachment", expires_in: 300 }
    })
  );
  return proxiedDownloadPath(signed.url, fileId);
}

/** A short-lived download path (through the app's proxy) for a file a run received as input. */
export async function inputFileDownloadPath(
  flowId: string,
  runId: string,
  fileId: string
): Promise<string> {
  const signed = await unwrap(
    browserApi.POST("/api/v1/flows/{id}/runs/{run_id}/input-files/{file_id}/signed-url/", {
      params: { path: { id: flowId, run_id: runId, file_id: fileId } },
      body: { content_disposition: "attachment", expires_in: 300 }
    })
  );
  return proxiedDownloadPath(signed.url, fileId);
}

export function activeReviewQueryOptions(flowId: string, runId: string, version: string) {
  return queryOptions({
    queryKey: runKeys.review(flowId, runId, version),
    queryFn: ({ signal }): Promise<ReviewCheckpoint | null> =>
      unwrap(
        browserApi.GET("/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/active/", {
          params: { path: { id: flowId, run_id: runId } },
          signal
        })
      ).then((checkpoint) => checkpoint ?? null)
  });
}

type CheckpointRef = Pick<ReviewCheckpoint, "flow_id" | "flow_run_id" | "id" | "revision">;

function checkpointPath(checkpoint: CheckpointRef) {
  return {
    id: checkpoint.flow_id,
    run_id: checkpoint.flow_run_id,
    checkpoint_id: checkpoint.id
  };
}

/** Saves the reviewer's version of the step's output: a string for text, JSON for JSON. */
export function editReview(
  checkpoint: CheckpointRef,
  editedValue: Schema<"FlowRunReviewCheckpointEditRequest">["edited_value"]
): Promise<ReviewCheckpoint> {
  return unwrap(
    browserApi.PATCH("/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/", {
      params: { path: checkpointPath(checkpoint) },
      body: { edited_value: editedValue, expected_checkpoint_revision: checkpoint.revision }
    })
  );
}

/** Approves the output as it stands and lets the run go on, in one request. */
export function approveAndContinue(
  checkpoint: CheckpointRef,
  idempotencyKey: string
): Promise<ReviewResume> {
  return unwrap(
    browserApi.POST(
      "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/approve-and-continue/",
      {
        params: {
          path: checkpointPath(checkpoint),
          header: { "Idempotency-Key": idempotencyKey }
        },
        body: { expected_checkpoint_revision: checkpoint.revision }
      }
    )
  );
}

/** Lets a run go on whose review was approved without it (another client approved only). */
export function resumeReview(
  checkpoint: CheckpointRef,
  idempotencyKey: string
): Promise<ReviewResume> {
  return unwrap(
    browserApi.POST("/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/resume/", {
      params: {
        path: checkpointPath(checkpoint),
        header: { "Idempotency-Key": idempotencyKey }
      },
      body: { expected_checkpoint_revision: checkpoint.revision }
    })
  );
}

/** Rejects the output; the run is cancelled with the reason in its audit trail. */
export function rejectReview(checkpoint: CheckpointRef, reason: string): Promise<ReviewCheckpoint> {
  return unwrap(
    browserApi.POST("/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/reject/", {
      params: { path: checkpointPath(checkpoint) },
      body: { expected_checkpoint_revision: checkpoint.revision, reason }
    })
  );
}

/** A fresh key for one logical write; a retry of the same write reuses it. */
export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}

export type TranscriptSourcePage = Schema<"PresentTranscriptSourcePage">;

/**
 * The transcript source of one transcription attempt, all pages read in
 * order: its raw lines, the hash corrections are anchored to, and its
 * speaker review. `omitted` and `unavailable` sources carry no lines.
 */
export async function getTranscriptSource(
  flowId: string,
  runId: string,
  target: { stepId: string; attemptNo: number },
  signal?: AbortSignal
): Promise<
  | { status: "present"; segments: TranscriptSourceSegment[]; sourceHash: string }
  | { status: "omitted"; tooLarge: boolean }
  | { status: "unavailable" }
> {
  const segments: TranscriptSourceSegment[] = [];
  let sourceHash: string | null = null;
  let start = 0;
  for (;;) {
    const page = await unwrap(
      browserApi.GET(
        "/api/v1/flows/{flow_id}/runs/{run_id}/steps/{step_id}/attempts/{attempt_no}/transcript-source/",
        {
          params: {
            path: {
              flow_id: flowId,
              run_id: runId,
              step_id: target.stepId,
              attempt_no: target.attemptNo
            },
            query: { start_segment_index: start }
          },
          signal
        }
      )
    );
    // A source too large to page; the other reasons have no lines to page.
    if (page.status === "omitted") {
      return { status: "omitted", tooLarge: page.reason === OMISSION_REASON.TOO_LARGE };
    }
    if (page.status !== "present") return { status: "unavailable" };
    sourceHash ??= page.source_hash;
    segments.push(...page.segments);
    if (page.next_segment_index === null) break;
    if (page.next_segment_index <= start)
      throw new Error("Transcript source paging did not advance");
    start = page.next_segment_index;
  }
  return { status: "present", segments, sourceHash: sourceHash ?? "" };
}

export function transcriptQueryOptions(
  flowId: string,
  runId: string,
  target: { stepId: string; attemptNo: number }
) {
  return queryOptions({
    queryKey: [...runKeys.run(flowId, runId), "transcript", target.stepId, target.attemptNo],
    queryFn: ({ signal }) => getTranscriptSource(flowId, runId, target, signal),
    // A finished attempt's source does not change.
    staleTime: Infinity
  });
}

export function transcriptCorrectionsQueryOptions(flowId: string, runId: string) {
  return queryOptions({
    queryKey: [...runKeys.run(flowId, runId), "transcript-corrections"],
    queryFn: ({ signal }) =>
      unwrap(
        browserApi.GET("/api/v1/flows/{id}/runs/{run_id}/transcript-corrections/", {
          params: { path: { id: flowId, run_id: runId } },
          signal
        })
      )
  });
}

/** Replaces one transcription step's corrections (the whole set, revision-fenced). */
export function editTranscriptCorrections(
  flowId: string,
  runId: string,
  stepId: string,
  body: Schema<"FlowTranscriptCorrectionsEditRequest">
) {
  return unwrap(
    browserApi.PATCH("/api/v1/flows/{id}/runs/{run_id}/steps/{step_id}/transcript-corrections/", {
      params: { path: { id: flowId, run_id: runId, step_id: stepId } },
      body
    })
  );
}
