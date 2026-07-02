const MEBIBYTE_BYTES = 1024 * 1024;
const CONSERVATIVE_FALLBACK_TIMEOUT_MS = 120_000;
const CONSERVATIVE_FALLBACK_TIMEOUT_SECONDS = CONSERVATIVE_FALLBACK_TIMEOUT_MS / 1000;

/** @param {number | null | undefined} value */
function positiveFinite(value) {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;
}

/**
 * @param {number} fileSizeBytes
 * @param {import("../types/resources").FlowRuntimeUploadPolicy | null | undefined} policy
 */
export function resolveFlowRuntimeUploadInitialTimeoutMs(fileSizeBytes, policy) {
  const minSeconds = positiveFinite(policy?.min_timeout_seconds);
  const secondsPerMebibyte = positiveFinite(policy?.seconds_per_mebibyte);
  const maxSeconds = positiveFinite(policy?.max_timeout_seconds);
  if (minSeconds == null || secondsPerMebibyte == null || maxSeconds == null) {
    return CONSERVATIVE_FALLBACK_TIMEOUT_MS;
  }

  const sizeMebibytes = Math.max(0, fileSizeBytes) / MEBIBYTE_BYTES;
  const estimatedSeconds = Math.ceil(sizeMebibytes * secondsPerMebibyte);
  const clampedSeconds = Math.min(maxSeconds, Math.max(minSeconds, estimatedSeconds));
  return clampedSeconds * 1000;
}

/**
 * @param {import("../types/resources").FlowRuntimeUploadPolicy | null | undefined} policy
 */
export function resolveFlowRuntimeUploadIdleTimeoutMs(policy) {
  const idleSeconds = positiveFinite(policy?.idle_timeout_seconds);
  return (idleSeconds ?? CONSERVATIVE_FALLBACK_TIMEOUT_SECONDS) * 1000;
}

/**
 * @param {{
 *   fileSizeBytes: number,
 *   policy: import("../types/resources").FlowRuntimeUploadPolicy | null | undefined,
 *   abortController: AbortController,
 *   onTimeout: (event: { reason: "not_started" | "stalled" | "server_not_responding", timeoutMs: number }) => void,
 *   setTimeoutFn?: typeof setTimeout,
 *   clearTimeoutFn?: typeof clearTimeout
 * }} params
 */
export function createFlowRuntimeUploadTimeoutController({
  fileSizeBytes,
  policy,
  abortController,
  onTimeout,
  setTimeoutFn = setTimeout,
  clearTimeoutFn = clearTimeout
}) {
  const initialTimeoutMs = resolveFlowRuntimeUploadInitialTimeoutMs(fileSizeBytes, policy);
  const idleTimeoutMs = resolveFlowRuntimeUploadIdleTimeoutMs(policy);
  let timeoutId = null;
  let lastUploadedBytes = 0;
  let active = true;

  const clearScheduledTimeout = () => {
    if (timeoutId) clearTimeoutFn(timeoutId);
    timeoutId = null;
  };

  const scheduleTimeout = (timeoutMs, reason) => {
    clearScheduledTimeout();
    timeoutId = setTimeoutFn(() => {
      if (!active) return;
      active = false;
      onTimeout({ reason, timeoutMs });
      abortController.abort();
    }, timeoutMs);
  };

  abortController.signal.addEventListener(
    "abort",
    () => {
      active = false;
      clearScheduledTimeout();
    },
    { once: true }
  );

  scheduleTimeout(initialTimeoutMs, "not_started");

  return {
    /** @param {Pick<ProgressEvent, "loaded" | "total" | "lengthComputable">} event */
    onProgress(event) {
      if (!active || event.loaded <= lastUploadedBytes) return;
      lastUploadedBytes = event.loaded;
      const uploadComplete =
        event.lengthComputable && event.total > 0 && event.loaded >= event.total;
      scheduleTimeout(idleTimeoutMs, uploadComplete ? "server_not_responding" : "stalled");
    },
    clear() {
      active = false;
      clearScheduledTimeout();
    }
  };
}
