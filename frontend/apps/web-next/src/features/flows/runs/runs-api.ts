import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";
import { browserApi, type EneoClient } from "@/lib/api/browser";
import { EneoApiError, unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { proxiedDownloadPath } from "@/features/files/signed-file-url";
import { OMISSION_REASON, type TranscriptSourceSegment } from "./transcript";
import type { TranscriptWords } from "./transcript-playback";

/**
 * The flow-core run endpoints the run screens use: the run contract, uploads,
 * starting, listing and following runs, their audited detail and steps,
 * cancel, retry and redispatch, downloads and human review.
 *
 * Content-free reads (the list, `/status/`, the run-pinned graph) are what
 * polling uses. Content reads are audited (`AUDITED_READ`, `auditedRead`).
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
export type EvidenceAccess = Schema<"FlowRunEvidenceAccessPublic">;
export type RunErrorWithGuidance = Schema<"FlowRunErrorPublic">;
export type TokenUsage = Schema<"FlowRunTokenUsagePublic">;
export type TranscriptionUsage = Schema<"FlowRunTranscriptionUsagePublic">;

/**
 * An audited content read kept for as long as it is cached: read when it is
 * opened, when its key changes, when it is invalidated (a save, Refresh),
 * never on a window focus, a reconnect or a remount. Only for a read whose
 * key names a version of what it reads: the run detail (keyed by the run's
 * progress), the word timings of a finished transcription, and a settled
 * run's steps and evidence (`auditedRead`).
 */
const AUDITED_READ = { staleTime: Infinity } as const;

/**
 * How long a run's steps and evidence are kept. While the run is live or
 * awaits review: the app's default, since a review checkpoint's edit or
 * approval changes them without moving the run's progress. Once the run is
 * settled (`isTerminal`, which their keys name): for good, since nothing
 * changes them any more. Transcript corrections and their history always keep
 * the default: they are saved, and speakers named, on a settled run too,
 * without moving it. So do the active review and its edits, which exist only
 * while a review is open.
 */
export function auditedRead(settled: boolean): { staleTime?: number } {
  return settled ? AUDITED_READ : {};
}

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
  /** `settled`: whether the run had settled (`isTerminal`) when this was read. */
  evidence: (flowId: string, runId: string, settled: boolean) =>
    ["flows", flowId, "runs", runId, "evidence", settled ? "settled" : "live"] as const,
  corrections: (flowId: string, runId: string) =>
    ["flows", flowId, "runs", runId, "transcript-corrections"] as const,
  revisions: (flowId: string, runId: string, stepId: string) =>
    ["flows", flowId, "runs", runId, "transcript-revisions", stepId] as const,
  /**
   * A run's transcript reads, each of one attempt: under the literal
   * "transcripts" (like "contract" and "list") rather than under `run`, so a
   * save or a refusal that reads the run again does not read every page of a
   * source that has not changed. Refresh reads them again.
   */
  transcripts: (flowId: string, runId: string) =>
    ["flows", flowId, "runs", "transcripts", runId] as const,
  transcriptSource: (flowId: string, runId: string, stepId: string, attemptNo: number) =>
    ["flows", flowId, "runs", "transcripts", runId, "source", stepId, attemptNo] as const,
  transcriptWords: (flowId: string, runId: string, stepId: string, attemptNo: number) =>
    ["flows", flowId, "runs", "transcripts", runId, "words", stepId, attemptNo] as const
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

/** How the list endpoint orders runs (start time, status or duration). */
export type RunsSort = { key: "started_at" | "status" | "duration"; order: "asc" | "desc" };
export type RunStatusCounts = Schema<"FlowRunStatusCountsPublic">;

/**
 * `mine`: only the runs the caller started, within those the caller may see.
 * `status`: only runs with this status. `search`: runs whose name or starter's
 * name contains it. `sort`: the order. The list endpoint does all of it, so
 * every page and "show more" stay within it.
 */
export type RunsFilter = {
  mine: boolean;
  status?: RunStatus | null;
  search?: string;
  sort?: RunsSort;
};

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
              ...(filter.status ? { status: [filter.status] } : {}),
              ...(filter.search ? { search: filter.search } : {}),
              ...(filter.sort ? { sort: filter.sort.key, order: filter.sort.order } : {}),
              // The list shows the first page's counts; counting the whole
              // history again for every older page would only be thrown away.
              ...(pageParam > 0 ? { include_status_counts: false } : {})
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
      ),
    ...AUDITED_READ
  });
}

/** The run's audited detail, read once (what "use the last run's input" fills the form from). */
export function getRunDetail(flowId: string, runId: string): Promise<RunDetail> {
  return unwrap(
    browserApi.GET("/api/v1/flows/{id}/runs/{run_id}/", {
      params: { path: { id: flowId, run_id: runId } }
    })
  );
}

/**
 * The newest run the caller started of this flow, from the content-free
 * list (`mine`, newest first), or null when the caller has none. It sits
 * under the list's key, so a new run refreshes it.
 */
export function lastOwnRunQueryOptions(flowId: string) {
  return queryOptions({
    queryKey: [...runKeys.list(flowId), "last-own"] as const,
    queryFn: async ({ signal }): Promise<RunSummary | null> => {
      const page = await unwrap(
        browserApi.GET("/api/v1/flows/{id}/runs/", {
          params: {
            path: { id: flowId },
            query: { limit: 1, mine: true, include_status_counts: false }
          },
          signal
        })
      );
      return page.items[0] ?? null;
    },
    staleTime: 0
  });
}

export function runStepsQueryOptions(
  flowId: string,
  runId: string,
  version: string,
  settled: boolean
) {
  return queryOptions({
    queryKey: runKeys.steps(flowId, runId, version),
    queryFn: ({ signal }): Promise<RunStep[]> =>
      unwrap(
        browserApi.GET("/api/v1/flows/{id}/runs/{run_id}/steps/", {
          params: { path: { id: flowId, run_id: runId } },
          signal
        })
      ),
    ...auditedRead(settled)
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

export function runEvidenceQueryOptions(flowId: string, runId: string, settled: boolean) {
  return queryOptions({
    queryKey: runKeys.evidence(flowId, runId, settled),
    queryFn: ({ signal }): Promise<RunEvidence> =>
      unwrap(
        browserApi.GET("/api/v1/flows/{id}/runs/{run_id}/evidence/", {
          params: { path: { id: flowId, run_id: runId } },
          signal
        })
      ),
    ...auditedRead(settled),
    // A bundle can be megabytes: not kept long once nothing shows it.
    gcTime: 60_000
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
export type TranscriptSpeakerReview = Schema<"TranscriptSpeakerReviewPublic">;

/** How many transcript source pages are read at once after the first. */
const TRANSCRIPT_SOURCE_PAGE_CONCURRENCY = 3;

/**
 * The transcript source of one transcription attempt, all pages read in
 * order: its raw lines, the hash corrections are anchored to, and its
 * speaker review. `omitted` and `unavailable` sources carry no lines.
 *
 * Pages are addressed by line index, so the first page's size and line count
 * say where the others start: they are requested a few at a time, then read
 * in order by `next_segment_index`, which still decides where the next page
 * starts (a page not requested in advance is requested then). One failed page
 * fails the read, starts no other and stops the requests still out, as
 * cancelling does.
 */
export async function getTranscriptSource(
  flowId: string,
  runId: string,
  target: { stepId: string; attemptNo: number },
  signal?: AbortSignal
): Promise<
  | {
      status: "present";
      segments: TranscriptSourceSegment[];
      sourceHash: string;
      speakerReview: TranscriptSpeakerReview | null;
    }
  | { status: "omitted"; tooLarge: boolean }
  | { status: "unavailable" }
> {
  const controller = new AbortController();
  const cancel = () => controller.abort(signal?.reason);
  if (signal?.aborted) cancel();
  signal?.addEventListener("abort", cancel);
  let active = 0;
  const waiting: (() => void)[] = [];
  const fetchPage = async (start: number) => {
    while (active >= TRANSCRIPT_SOURCE_PAGE_CONCURRENCY) {
      await new Promise<void>((resume) => waiting.push(resume));
    }
    active += 1;
    try {
      controller.signal.throwIfAborted();
      return await unwrap(
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
            signal: controller.signal
          }
        )
      );
    } catch (error) {
      // A failed page fails the read with its own error, before its slot goes
      // to a page queued behind it: that page and the ones still out stop. A
      // page stopped that way may reject with a bare AbortError, so every page
      // rethrows the first reason: the read fails with the error that ended it.
      controller.abort(error);
      throw controller.signal.reason;
    } finally {
      active -= 1;
      waiting.shift()?.();
    }
  };
  try {
    const segments: TranscriptSourceSegment[] = [];
    let sourceHash: string | null = null;
    let speakerReview: TranscriptSpeakerReview | null = null;
    let start = 0;
    let page = await fetchPage(start);
    const requested = new Map<number, ReturnType<typeof fetchPage>>();
    for (;;) {
      // A source too large to page; the other reasons have no lines to page.
      if (page.status === "omitted") {
        return { status: "omitted", tooLarge: page.reason === OMISSION_REASON.TOO_LARGE };
      }
      if (page.status !== "present") return { status: "unavailable" };
      sourceHash ??= page.source_hash;
      // The speaker review comes with the first page only.
      speakerReview ??= page.speaker_review ?? null;
      segments.push(...page.segments);
      if (page.next_segment_index === null) break;
      if (page.next_segment_index <= start)
        throw new Error("Transcript source paging did not advance");
      if (start === 0 && page.page_size > 0) {
        for (
          let next = page.next_segment_index;
          next < page.bounds.segments_count;
          next += page.page_size
        ) {
          const request = fetchPage(next);
          // Not left unhandled: its failure ends the read through the
          // controller, whether or not the read reaches it.
          request.catch(() => undefined);
          requested.set(next, request);
        }
      }
      start = page.next_segment_index;
      page = await (requested.get(start) ?? fetchPage(start));
    }
    return { status: "present", segments, sourceHash: sourceHash ?? "", speakerReview };
  } finally {
    signal?.removeEventListener("abort", cancel);
    // Stops pages requested in advance that the read did not reach.
    controller.abort();
  }
}

export function transcriptQueryOptions(
  flowId: string,
  runId: string,
  target: { stepId: string; attemptNo: number }
) {
  return queryOptions({
    queryKey: runKeys.transcriptSource(flowId, runId, target.stepId, target.attemptNo),
    queryFn: ({ signal }) => getTranscriptSource(flowId, runId, target, signal),
    // A finished attempt's source does not change.
    staleTime: Infinity
  });
}

/**
 * The word timings a transcription step stored, or null when it stored
 * none. An audited content read: asked for once someone plays the audio.
 * The endpoint answers for the step's current attempt; the key names the
 * attempt the transcript shows, so another attempt is read afresh (a "none"
 * included). Words of another source are never placed (`wordsByLine`
 * checks the hash).
 */
export function transcriptWordsQueryOptions(
  flowId: string,
  runId: string,
  target: { stepId: string; attemptNo: number }
) {
  return queryOptions({
    queryKey: runKeys.transcriptWords(flowId, runId, target.stepId, target.attemptNo),
    queryFn: async ({ signal }): Promise<TranscriptWords | null> => {
      try {
        return await unwrap(
          browserApi.GET("/api/v1/flows/{id}/runs/{run_id}/steps/{step_id}/transcript-words/", {
            params: { path: { id: flowId, run_id: runId, step_id: target.stepId } },
            signal
          })
        );
      } catch (error) {
        if (error instanceof EneoApiError && error.status === 404) return null;
        throw error;
      }
    },
    ...AUDITED_READ
  });
}

/**
 * A short-lived path (through the app's proxy) that plays an audio file the
 * run received, and when it runs out (epoch ms; null when the core did not
 * say).
 */
export async function inputFilePlayback(
  flowId: string,
  runId: string,
  fileId: string
): Promise<{ path: string; expiresAt: number | null }> {
  const signed = await unwrap(
    browserApi.POST("/api/v1/flows/{id}/runs/{run_id}/input-files/{file_id}/signed-url/", {
      params: { path: { id: flowId, run_id: runId, file_id: fileId } },
      body: { content_disposition: "inline", expires_in: 3600 }
    })
  );
  const expiresAt = Number.isFinite(signed.expires_at) ? signed.expires_at * 1000 : null;
  return { path: proxiedDownloadPath(signed.url, fileId), expiresAt };
}

export function transcriptCorrectionsQueryOptions(flowId: string, runId: string) {
  return queryOptions({
    queryKey: runKeys.corrections(flowId, runId),
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

export type CorrectionRevision = Schema<"FlowTranscriptCorrectionRevisionPublic">;
export type TranscriptRegeneration = Schema<"FlowTranscriptRegenerationPublic">;

/** Revisions per page of a step's correction history. */
export const REVISIONS_PAGE_SIZE = 20;

/**
 * Every saved version of a step's transcript corrections, oldest first, a
 * page at a time. A save adds one: it invalidates `runKeys.revisions`.
 */
export function transcriptRevisionsQueryOptions(flowId: string, runId: string, stepId: string) {
  return infiniteQueryOptions({
    queryKey: runKeys.revisions(flowId, runId, stepId),
    queryFn: ({ pageParam, signal }) =>
      unwrap(
        browserApi.GET(
          "/api/v1/flows/{id}/runs/{run_id}/transcript-corrections/{step_id}/revisions",
          {
            params: {
              path: { id: flowId, run_id: runId, step_id: stepId },
              query: {
                limit: REVISIONS_PAGE_SIZE,
                ...(pageParam !== null ? { after_revision: pageParam } : {})
              }
            },
            signal
          }
        )
      ),
    initialPageParam: null as number | null,
    getNextPageParam: (last) => last.next_after_revision
  });
}

/**
 * Starts a new run of the flow from this run's reviewed transcript: the
 * transcription (and a speaker-mapping step after it) is taken as reviewed,
 * and every later step runs again. Fenced by the run's and the corrections'
 * revisions; a retry with the same key answers the run it already started.
 */
export function regenerateTranscript(
  flowId: string,
  runId: string,
  stepId: string,
  body: Schema<"FlowTranscriptRegenerationRequest">,
  idempotencyKey: string
): Promise<TranscriptRegeneration> {
  return unwrap(
    browserApi.POST("/api/v1/flows/{id}/runs/{run_id}/steps/{step_id}/transcript-regenerations/", {
      params: {
        path: { id: flowId, run_id: runId, step_id: stepId },
        header: { "Idempotency-Key": idempotencyKey }
      },
      body
    })
  );
}

export type LiveTranscriptionSession = Schema<"FlowLiveTranscriptionSessionPublic">;

/**
 * Admits a live transcript of a recording for one audio step: a single-use
 * ticket for the socket. `recordingId` names a recording whose transcript the
 * core may store when the session hears all of it.
 */
export function openLiveTranscription(
  flowId: string,
  stepId: string,
  recordingId?: string
): Promise<LiveTranscriptionSession> {
  return unwrap(
    browserApi.POST("/api/v1/flows/{id}/steps/{step_id}/live-transcription-sessions/", {
      params: { path: { id: flowId, step_id: stepId } },
      body: recordingId ? { recording_id: recordingId } : null
    })
  );
}

/**
 * The live transcription socket on the app's own origin: the browser never
 * reaches the backend directly, and `src/proxy.ts` hands this one path over
 * to it (the REST proxy cannot carry a WebSocket).
 */
export function liveSocketUrl(
  websocketPath: string,
  location: Pick<Location, "protocol" | "host"> = window.location
): string {
  return `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/api/eneo${websocketPath}`;
}
