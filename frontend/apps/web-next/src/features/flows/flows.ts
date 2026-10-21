import { infiniteQueryOptions, queryOptions, type QueryClient } from "@tanstack/react-query";
import { EneoApiError, unwrap } from "@/lib/api/errors";
import { flowsApi } from "./flows-api";
import type {
  FlowDefinition,
  FlowPublic,
  FlowRunCreateRequest,
  FlowRunPublic,
  FlowRunReviewCheckpointPublic,
  FlowRunStatus,
  StepResultStatus
} from "./types";

/** Runs the panel polls while they can still change. */
export const ACTIVE_RUN_STATUSES: readonly FlowRunStatus[] = [
  "queued",
  "running",
  "awaiting_review"
];

export function isActiveRun(status: FlowRunStatus | null | undefined): boolean {
  return status !== undefined && status !== null && ACTIVE_RUN_STATUSES.includes(status);
}

/** A step the run has not finished with yet. */
export function isActiveStep(status: StepResultStatus): boolean {
  return status === "pending" || status === "running" || status === "awaiting_review";
}

/** Checkpoints a person can still decide on. */
export function isOpenCheckpoint(checkpoint: FlowRunReviewCheckpointPublic | null | undefined) {
  return checkpoint?.state === "awaiting_review" || checkpoint?.state === "edited";
}

export const RUNS_PAGE_SIZE = 20;
/** Revisions the history tab lists at a time (newest first). */
export const REVISIONS_PAGE_SIZE = 20;
/** How often an active run is refetched while the tab is visible. */
export const RUN_POLL_INTERVAL_MS = 3000;

export const flowKeys = {
  all: ["flows"] as const,
  list: (spaceId: string) => ["flows", "list", spaceId] as const,
  artifacts: (flowId: string) => ["flows", flowId, "artifacts"] as const,
  authoringAssistant: (spaceId: string) => ["flows", "authoring-assistant", spaceId] as const,
  flow: (flowId: string) => ["flows", flowId] as const,
  contract: (flowId: string, version: number | null | undefined) =>
    ["flows", flowId, "contract", version] as const,
  runs: (flowId: string) => ["flows", flowId, "runs"] as const,
  run: (flowId: string, runId: string) => ["flows", flowId, "runs", runId] as const,
  transcript: (flowId: string, runId: string, stepId: string) =>
    ["flows", flowId, "runs", runId, "transcript", stepId] as const,
  revisions: (flowId: string) => ["flows", flowId, "revisions"] as const,
  revision: (flowId: string, revision: number) => ["flows", flowId, "revisions", revision] as const
};

export function flowTranscriptQueryOptions(flowId: string, runId: string, stepId: string) {
  return queryOptions({
    queryKey: flowKeys.transcript(flowId, runId, stepId),
    queryFn: ({ signal }) =>
      unwrap(
        flowsApi.GET("/api/v1/flows/{id}/runs/{run_id}/steps/{step_id}/transcript/", {
          params: { path: { id: flowId, run_id: runId, step_id: stepId } },
          signal
        })
      )
  });
}

export function flowsListQueryOptions(spaceId: string) {
  return queryOptions({
    queryKey: flowKeys.list(spaceId),
    queryFn: ({ signal }) =>
      unwrap(flowsApi.GET("/api/v1/flows/", { params: { query: { space_id: spaceId } }, signal }))
  });
}

/** The hidden assistant a space's flows are authored with (created on first call). */
export function authoringAssistantQueryOptions(spaceId: string) {
  return queryOptions({
    queryKey: flowKeys.authoringAssistant(spaceId),
    queryFn: ({ signal }) =>
      unwrap(
        flowsApi.GET("/api/v1/flows/authoring-assistant/", {
          params: { query: { space_id: spaceId } },
          signal
        })
      ),
    staleTime: Infinity
  });
}

export function flowQueryOptions(flowId: string) {
  return queryOptions({
    queryKey: flowKeys.flow(flowId),
    queryFn: ({ signal }) =>
      unwrap(flowsApi.GET("/api/v1/flows/{id}/", { params: { path: { id: flowId } }, signal }))
  });
}

export function flowRunContractQueryOptions(flowId: string, version: number | null | undefined) {
  return queryOptions({
    queryKey: flowKeys.contract(flowId, version),
    queryFn: ({ signal }) =>
      unwrap(
        flowsApi.GET("/api/v1/flows/{id}/run-contract/", {
          params: { path: { id: flowId } },
          signal
        })
      )
  });
}

export function publishFlow(flow: FlowPublic): Promise<FlowPublic> {
  return unwrap(
    flowsApi.POST("/api/v1/flows/{id}/publish/", {
      params: { path: { id: flow.id } },
      body: { expected_revision: flow.revision ?? 1 }
    })
  );
}

export function unpublishFlow(flow: FlowPublic): Promise<FlowPublic> {
  return unwrap(
    flowsApi.POST("/api/v1/flows/{id}/unpublish/", {
      params: { path: { id: flow.id } },
      body: { expected_revision: flow.revision ?? 1 }
    })
  );
}

/** Files the flow's runs produced, newest first (a result is found here after its run). */
export function flowArtifactsQueryOptions(flowId: string) {
  return queryOptions({
    queryKey: flowKeys.artifacts(flowId),
    queryFn: ({ signal }) =>
      unwrap(
        flowsApi.GET("/api/v1/flows/{id}/artifacts/", { params: { path: { id: flowId } }, signal })
      )
  });
}

/** Newest runs first, a page at a time (offset pagination, as the backend lists them). */
export function flowRunsQueryOptions(flowId: string) {
  return infiniteQueryOptions({
    queryKey: flowKeys.runs(flowId),
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      unwrap(
        flowsApi.GET("/api/v1/flows/{id}/runs/", {
          params: { path: { id: flowId }, query: { limit: RUNS_PAGE_SIZE, offset: pageParam } },
          signal
        })
      ),
    getNextPageParam: (last, pages) =>
      last.items.length < RUNS_PAGE_SIZE ? undefined : pages.length * RUNS_PAGE_SIZE
  });
}

/**
 * One run with its steps. While it is queued, running or waiting for a
 * review it is refetched every few seconds; TanStack pauses the interval in
 * a hidden tab (`refetchIntervalInBackground` is off).
 */
export function flowRunQueryOptions(flowId: string, runId: string) {
  return queryOptions({
    queryKey: flowKeys.run(flowId, runId),
    queryFn: ({ signal }) =>
      unwrap(
        flowsApi.GET("/api/v1/flows/{id}/runs/{run_id}/", {
          params: { path: { id: flowId, run_id: runId } },
          signal
        })
      ),
    refetchInterval: (query) =>
      isActiveRun(query.state.data?.status) &&
      (typeof document === "undefined" || document.visibilityState === "visible")
        ? RUN_POLL_INTERVAL_MS
        : false
  });
}

/** The flow's history, newest first, a page at a time. */
export function flowRevisionsQueryOptions(flowId: string) {
  return infiniteQueryOptions({
    queryKey: flowKeys.revisions(flowId),
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      unwrap(
        flowsApi.GET("/api/v1/flows/{id}/revisions/", {
          params: {
            path: { id: flowId },
            query: { limit: REVISIONS_PAGE_SIZE, offset: pageParam }
          },
          signal
        })
      ),
    getNextPageParam: (last, pages) =>
      last.items.length < REVISIONS_PAGE_SIZE ? undefined : pages.length * REVISIONS_PAGE_SIZE
  });
}

/** One revision with its definition. A revision never changes once written. */
export function flowRevisionQueryOptions(flowId: string, revision: number) {
  return queryOptions({
    queryKey: flowKeys.revision(flowId, revision),
    queryFn: ({ signal }) =>
      unwrap(
        flowsApi.GET("/api/v1/flows/{id}/revisions/{revision}/", {
          params: { path: { id: flowId, revision } },
          signal
        })
      ),
    staleTime: Infinity
  });
}

/** Makes the revision the draft again; the restore is a new revision. */
export function restoreFlowRevision(
  flowId: string,
  revision: number,
  expectedRevision: number
): Promise<FlowPublic> {
  return unwrap(
    flowsApi.POST("/api/v1/flows/{id}/revisions/{revision}/restore/", {
      params: { path: { id: flowId, revision } },
      body: { expected_revision: expectedRevision }
    })
  );
}

export function createFlowRun(flowId: string, body: FlowRunCreateRequest): Promise<FlowRunPublic> {
  return unwrap(
    flowsApi.POST("/api/v1/flows/{id}/runs/", { params: { path: { id: flowId } }, body })
  );
}

export function cancelFlowRun(flowId: string, runId: string): Promise<FlowRunPublic> {
  return unwrap(
    flowsApi.POST("/api/v1/flows/{id}/runs/{run_id}/cancel/", {
      params: { path: { id: flowId, run_id: runId } }
    })
  );
}

/** What the panel's editor sends: only the fields given change; the note goes to the history. */
export type FlowUpdate = {
  expected_revision: number;
  name?: string;
  description?: string;
  definition?: FlowDefinition;
  note?: string | null;
};

/** Saves a change from the panel as a new draft revision (channel "api"); needs edit mode. */
export function updateFlow(flowId: string, body: FlowUpdate): Promise<FlowPublic> {
  return unwrap(flowsApi.PATCH("/api/v1/flows/{id}/", { params: { path: { id: flowId } }, body }));
}

/** The user presses "Redigera": the flow (and its chat) may change until "Klar". */
export function enterEditMode(flowId: string): Promise<FlowPublic> {
  return unwrap(
    flowsApi.POST("/api/v1/flows/{id}/edit-mode/", { params: { path: { id: flowId } } })
  );
}

export function leaveEditMode(flowId: string): Promise<FlowPublic> {
  return unwrap(
    flowsApi.DELETE("/api/v1/flows/{id}/edit-mode/", { params: { path: { id: flowId } } })
  );
}

/**
 * The problems a save was refused for (a 422 from the validator), each one
 * line, or null for any other failure. The editor shows them at the fields
 * they name instead of as a toast.
 */
export function definitionProblems(error: unknown): string[] | null {
  if (!(error instanceof EneoApiError) || error.status !== 422) return null;
  const details = error.details;
  if (!details || typeof details !== "object") return null;
  const problems = (details as { problems?: unknown }).problems;
  return Array.isArray(problems) && problems.every((item) => typeof item === "string")
    ? (problems as string[])
    : null;
}

/** Whether a request was refused because the flow is in view mode (409). */
export function isViewModeError(error: unknown): boolean {
  return error instanceof EneoApiError && error.reason === "flow_not_in_edit_mode";
}

export function deleteFlow(flowId: string): Promise<unknown> {
  return unwrap(flowsApi.DELETE("/api/v1/flows/{id}/", { params: { path: { id: flowId } } }));
}

type CheckpointRef = { flowId: string; runId: string; checkpointId: string; revision: number };

const checkpointPath = ({ flowId, runId, checkpointId }: CheckpointRef) => ({
  id: flowId,
  run_id: runId,
  checkpoint_id: checkpointId
});

/** Saves an edited review payload; the returned checkpoint carries the next revision. */
export function editCheckpoint(ref: CheckpointRef, currentPayload: Record<string, unknown>) {
  return unwrap(
    flowsApi.PATCH("/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/", {
      params: { path: checkpointPath(ref) },
      body: { expected_checkpoint_revision: ref.revision, current_payload_json: currentPayload }
    })
  );
}

export function approveCheckpointAndContinue(ref: CheckpointRef) {
  return unwrap(
    flowsApi.POST(
      "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/approve-and-continue/",
      {
        params: { path: checkpointPath(ref) },
        body: { expected_checkpoint_revision: ref.revision }
      }
    )
  );
}

export function rejectCheckpoint(ref: CheckpointRef, reason: string | null) {
  return unwrap(
    flowsApi.POST("/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/reject/", {
      params: { path: checkpointPath(ref) },
      body: { expected_checkpoint_revision: ref.revision, reason }
    })
  );
}

/**
 * Refetches everything shown about a flow after a tool call changed it: the
 * flow itself and, by key prefix, its runs and its revision history.
 */
export function invalidateFlow(queryClient: QueryClient, flowId: string) {
  return queryClient.invalidateQueries({ queryKey: flowKeys.flow(flowId) });
}

export function invalidateFlowLists(queryClient: QueryClient) {
  return queryClient.invalidateQueries({ queryKey: ["flows", "list"] });
}
