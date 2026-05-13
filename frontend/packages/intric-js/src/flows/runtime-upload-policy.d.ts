import type { FlowRuntimeUploadPolicy } from "../types/resources";

export function resolveFlowRuntimeUploadInitialTimeoutMs(
  fileSizeBytes: number,
  policy: FlowRuntimeUploadPolicy | null | undefined
): number;

export function resolveFlowRuntimeUploadIdleTimeoutMs(
  policy: FlowRuntimeUploadPolicy | null | undefined
): number;

export type FlowRuntimeUploadTimeoutReason = "not_started" | "stalled" | "server_not_responding";

export type FlowRuntimeUploadTimeoutEvent = {
  reason: FlowRuntimeUploadTimeoutReason;
  timeoutMs: number;
};

export function createFlowRuntimeUploadTimeoutController(params: {
  fileSizeBytes: number;
  policy: FlowRuntimeUploadPolicy | null | undefined;
  abortController: AbortController;
  onTimeout: (event: FlowRuntimeUploadTimeoutEvent) => void;
  setTimeoutFn?: typeof setTimeout;
  clearTimeoutFn?: typeof clearTimeout;
}): {
  onProgress: (event: Pick<ProgressEvent, "loaded" | "total" | "lengthComputable">) => void;
  clear: () => void;
};
