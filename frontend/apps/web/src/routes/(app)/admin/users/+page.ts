export const load = async (event) => {
  const { intric } = await event.parent();

  // Stable dependency key for manual invalidation after mutations
  event.depends("admin:users");

  // Read search and tab parameters from URL for server-side filtering.
  // Support both canonical `search` and legacy `search_email` links.
  const search_email =
    event.url.searchParams.get('search') ||
    event.url.searchParams.get('search_email') ||
    undefined;
  const tab = event.url.searchParams.get('tab') || 'active';  // Default to 'active' tab

  // Convert tab to state_filter for backend
  // 'active' tab shows ACTIVE + INVITED users (users who can log in)
  // 'inactive' tab shows INACTIVE users (temporary leave)
  const state_filter = tab === 'inactive' ? 'inactive' : 'active';

  // Backend now returns { items: User[], metadata: PaginationMetadata }
  const response = await intric.users.list({
    includeDetails: true,
    search_email,  // Server-side search
    state_filter   // Server-side state filtering
  });

  // Extract items, pagination, and state counts from response
  const users = response.items || [];
  const pagination = response.metadata || null;
  const counts = response.metadata?.counts || null;

  return {
    users,
    pagination,
    counts  // State counts for tab display (active, inactive)
  };
};
