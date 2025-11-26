// Disable SSR to ensure authentication cookies work reliably during browser refreshes
// This forces the load function to run in the browser where credentials: 'include' is effective
export const ssr = false;

export const load = async (event) => {
  const { intric } = await event.parent();

  try {
    // Read filter parameters from URL (aligned with backend API)
    const page = parseInt(event.url.searchParams.get("page") || "1");
    const page_size = parseInt(event.url.searchParams.get("page_size") || "100");
    const from_date = event.url.searchParams.get("from_date") || undefined;
    const to_date = event.url.searchParams.get("to_date") || undefined;
    const action = event.url.searchParams.get("action") || undefined;
    const actor_id = event.url.searchParams.get("actor_id") || undefined;

    // Fetch audit logs and retention policy in parallel
    // Session cookie (if present) is automatically sent with request
    const [response, retentionPolicy] = await Promise.all([
      intric.audit.list({
        page,
        page_size,
        from_date,
        to_date,
        action: action !== "all" ? action : undefined,
        actor_id,
      }),
      intric.audit.getRetentionPolicy(),
    ]);

    return {
      logs: response.logs || [],
      total_count: response.total_count || 0,
      page: response.page || 1,
      page_size: response.page_size || 100,
      total_pages: response.total_pages || 0,
      hasSession: true, // Successfully loaded logs = valid session
      error: null,
      retentionPolicy,
    };
  } catch (error: any) {
    // Check if error is 401 (no session/justification required)
    // Updated from 403 to match backend error codes
    const needsJustification = error?.status === 401;

    // Only log actual errors, not expected auth challenges
    if (!needsJustification) {
      console.error("Failed to load audit logs:", error);
    }

    // Fetch retention policy separately (doesn't require session)
    let retentionPolicy = null;
    try {
      retentionPolicy = await intric.audit.getRetentionPolicy();
    } catch (err) {
      console.error("Failed to fetch retention policy:", err);
    }

    return {
      logs: [],
      total_count: 0,
      page: 1,
      page_size: 100,
      total_pages: 0,
      hasSession: false, // No valid session
      error: needsJustification ? null : "Failed to load audit logs. Please try again.",
      retentionPolicy,
    };
  }
};
