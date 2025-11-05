export const load = async (event) => {
  const { intric } = await event.parent();

  event.depends("admin:users:load");

  // Read search parameter from URL for server-side search across all users
  const search_email = event.url.searchParams.get('search') || undefined;

  // Backend now returns { items: User[], metadata: PaginationMetadata }
  const response = await intric.users.list({
    includeDetails: true,
    search_email  // Server-side search across all 2831 users
  });

  // Extract items array (handle empty results properly)
  const users = Array.isArray(response) ? response : (response.items || []);

  return {
    users,  // Return array directly (matching original pattern)
    pagination: response.metadata || null
  };
};
