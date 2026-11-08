// @ts-check
import { EneoError } from "../client/client.js";

/** The backend's machine-readable code; UI wording remains in each app.
 * @param {unknown} error
 * @returns {string | null}
 */
export function widgetErrorCode(error) {
  if (!(error instanceof EneoError)) return null;
  /** @type {unknown} */
  const response = error.response;
  if (!response || typeof response !== "object" || !("detail" in response)) return null;
  const detail = response.detail;
  return detail && typeof detail === "object" && "code" in detail && typeof detail.code === "string"
    ? detail.code
    : null;
}
