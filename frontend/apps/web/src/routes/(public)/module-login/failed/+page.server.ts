import type { PageServerLoad } from "./$types";

const FAILURE_REASONS = new Set(["invalid_request", "module_unavailable", "service_unavailable"]);

export const load: PageServerLoad = ({ url, setHeaders }) => {
  setHeaders({
    "Cache-Control": "private, no-store, max-age=0",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow, noarchive"
  });
  const requestedReason = url.searchParams.get("reason");

  return {
    reason:
      requestedReason !== null && FAILURE_REASONS.has(requestedReason)
        ? requestedReason
        : "invalid_request"
  };
};
