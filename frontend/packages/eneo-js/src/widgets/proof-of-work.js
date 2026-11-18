// @ts-check
import { solveChallengeWorkers } from "altcha/lib";
import { EneoError } from "../client/client.js";

/** Includes fetching the challenge and starting its worker, not just hashing. */
export const VERIFICATION_TIMEOUT_MS = 30_000;

export class AltchaSolveError extends EneoError {
  constructor() {
    super("Widget verification failed", "CONNECTION", 0, 0, {
      detail: { code: "challenge_invalid" }
    });
    this.name = "AltchaSolveError";
  }
}

/**
 * Solve the backend's signed ALTCHA challenge with the vendor's solver and worker.
 * No hidden form, global registry, inline styles or blob worker participates.
 * One worker per verification; every exit terminates it, including a worker
 * that never answers. The server remains the authority on signatures/replay.
 *
 * @param {Pick<import("../../index.js").WidgetClient, "challenge">} client
 * @param {{signal?: AbortSignal}} [options]
 * @returns {Promise<string>}
 */
export async function solveWithAltcha(client, { signal } = {}) {
  const controller = new AbortController();
  /** @type {Set<Worker>} */
  const workers = new Set();
  /** @type {(reason: Error) => void} */
  let fail = () => {};
  /** @type {Promise<never>} */
  const interrupted = new Promise((_, reject) => {
    fail = reject;
  });
  const stop = () => {
    controller.abort();
    for (const worker of workers) worker.terminate();
    fail(new AltchaSolveError());
  };
  const timeout = setTimeout(stop, VERIFICATION_TIMEOUT_MS);
  signal?.addEventListener("abort", stop, { once: true });

  try {
    if (signal?.aborted) throw new AltchaSolveError();
    return await Promise.race([
      interrupted,
      (async () => {
        const raw = await client.challenge({ signal: controller.signal });
        // The SDK schema describes the algorithm-specific parameters as a
        // record. ALTCHA validates them; the server verifies the signed proof.
        const challenge = /** @type {import("altcha/lib").Challenge} */ (
          /** @type {unknown} */ (raw)
        );
        if (controller.signal.aborted) throw new AltchaSolveError();
        const solution = await solveChallengeWorkers({
          challenge,
          concurrency: 1,
          controller,
          timeout: VERIFICATION_TIMEOUT_MS,
          createWorker: (algorithm) => {
            if (algorithm !== "SHA-256" || controller.signal.aborted) {
              throw new AltchaSolveError();
            }
            const worker = new Worker(new URL("altcha/workers/sha", import.meta.url));
            workers.add(worker);
            return worker;
          }
        });
        if (!solution || controller.signal.aborted) throw new AltchaSolveError();
        return btoa(
          JSON.stringify({
            challenge: { parameters: challenge.parameters, signature: challenge.signature },
            solution
          })
        );
      })()
    ]);
  } catch (error) {
    if (error instanceof EneoError) throw error;
    throw new AltchaSolveError();
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", stop);
    controller.abort();
    for (const worker of workers) worker.terminate();
  }
}
