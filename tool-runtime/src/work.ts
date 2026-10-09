import { createHash } from "node:crypto";
import { AsyncLocalStorage } from "node:async_hooks";
import { ToolError } from "./errors";

export type Work = {
  group: string;
  requestId: string;
  signal: AbortSignal;
  cleanup: Array<() => void | Promise<void>>;
};
/** Identity policy is separate from scheduling; future single-tenant callers can change this mapping. */
export function callerGroup(tenantId: string): string {
  return tenantId ? createHash("sha256").update(tenantId).digest("hex") : "legacy";
}
export const work = new AsyncLocalStorage<Work>();
export function checkCancellation(signal = work.getStore()?.signal): void {
  if (signal?.aborted)
    throw signal.reason instanceof ToolError
      ? signal.reason
      : new ToolError("CANCELLED", "The operation was cancelled.");
}
/** Operational fields only: callers must never pass input, URLs, or credentials. */
export function event(name: string, fields: Record<string, string | number | boolean> = {}): void {
  console.log(JSON.stringify({ event: name, request_id: work.getStore()?.requestId, ...fields }));
}

/** Cancel a waiter without cancelling another call's shared cache build. */
export function waitFor<T>(operation: Promise<T>, signal = work.getStore()?.signal): Promise<T> {
  checkCancellation(signal);
  if (!signal) return operation;
  return new Promise<T>((resolve, reject) => {
    const abort = () =>
      reject(signal.reason ?? new ToolError("CANCELLED", "The operation was cancelled."));
    signal.addEventListener("abort", abort, { once: true });
    operation.then(resolve, reject).finally(() => signal.removeEventListener("abort", abort));
    if (signal.aborted) abort();
  });
}
