/**
 * Proof of work for widget visitors, solved by the ALTCHA widget element in
 * invisible mode. The element fetches the challenge from the widget's
 * challenge URL itself; we only trigger verification and read the payload.
 *
 * The "external" build is used on purpose: the default one writes a <style>
 * into its shadow root and spawns its solver from a blob: URL, both of
 * which a nonce-only CSP refuses. The external build registers nothing, so
 * the one algorithm the backend issues (altcha_service.ALGORITHM) gets its
 * worker here, bundled as a same-origin script.
 */
import type { AltchaWidgetElement } from "altcha/external";

type AltchaRegistry = { algorithms: Map<string, () => Worker> };

export class AltchaSolveError extends Error {
  constructor(message = "Proof of work failed") {
    super(message);
    this.name = "AltchaSolveError";
  }
}

/** Defines the `altcha-widget` element and its SHA-256 solver, once. */
export async function loadAltcha(): Promise<void> {
  await import("altcha/external");
  const registry = (globalThis as { $altcha?: AltchaRegistry }).$altcha;
  if (registry && !registry.algorithms.has("SHA-256")) {
    registry.algorithms.set(
      "SHA-256",
      () => new Worker(new URL("altcha/workers/sha", import.meta.url))
    );
  }
}

export async function solveWithAltcha(element: AltchaWidgetElement | null): Promise<string> {
  if (!element) throw new AltchaSolveError("ALTCHA widget is not mounted");
  const result = await element.verify();
  const payload = result?.payload;
  if (!payload) {
    throw new AltchaSolveError();
  }
  // Each payload is single-use server-side; reset so the next solve starts clean.
  element.reset();
  return payload;
}
