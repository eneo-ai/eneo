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

    // Read justification parameters (required for compliance tracking)
    const justification_category = event.url.searchParams.get("justification_category") || undefined;
    const justification_description = event.url.searchParams.get("justification_description") || undefined;

    // Create justification object if both params present (for state initialization)
    const justification = (justification_category && justification_description) ? {
      category: justification_category,
      description: justification_description,
      timestamp: new Date().toISOString()
    } : null;

    // Don't fetch logs without justification (prevents creating audit log entries without access reason)
    if (!justification) {
      return {
        logs: [],
        total_count: 0,
        page: 1,
        page_size: 100,
        total_pages: 0,
        justification: null,
        error: null,
      };
    }

    // Fetch audit logs with filters and justification
    const response = await intric.audit.list({
      page,
      page_size,
      from_date,
      to_date,
      action: action !== "all" ? action : undefined,
      actor_id,
      justification_category,
      justification_description,
    });

    return {
      logs: response.logs || [],
      total_count: response.total_count || 0,
      page: response.page || 1,
      page_size: response.page_size || 100,
      total_pages: response.total_pages || 0,
      justification,
      error: null,
    };
  } catch (error) {
    console.error("Failed to load audit logs:", error);
    return {
      logs: [],
      total_count: 0,
      page: 1,
      page_size: 100,
      total_pages: 0,
      justification: null,
      error: "Failed to load audit logs. Please try again.",
    };
  }
};
