/**
 * Proof of work for widget visitors, solved by the ALTCHA widget element in
 * invisible mode. The element fetches the challenge from the widget's
 * challenge URL itself; we only trigger verification and read the payload.
 */
import type { AltchaWidgetElement } from "altcha";

export class AltchaSolveError extends Error {
  constructor(message = "Proof of work failed") {
    super(message);
    this.name = "AltchaSolveError";
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
