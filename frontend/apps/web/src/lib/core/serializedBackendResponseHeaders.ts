// Keep in sync with backend response headers read by @intric/intric-js errors during SSR.
const serializedBackendResponseHeaders = new Set([
  "x-trace-id",
  "x-correlation-id",
  "x-error-code"
]);

export function shouldSerializeBackendResponseHeader(name: string): boolean {
  return serializedBackendResponseHeaders.has(name.toLowerCase());
}
