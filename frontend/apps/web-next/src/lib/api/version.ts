/**
 * The backend version from `GET /version`, which answers `{ "version": "…" }`
 * (the OpenAPI spec leaves the body untyped). "" when the answer has none.
 */
export function backendVersionFrom(body: unknown): string {
  if (typeof body !== "object" || body === null || !("version" in body)) return "";
  return typeof body.version === "string" ? body.version : "";
}
