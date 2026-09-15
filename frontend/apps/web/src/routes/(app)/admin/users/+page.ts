import { error } from "@sveltejs/kit";
import { m } from "$lib/paraglide/messages";
import { normalizeLocalPasswordCapability } from "$lib/features/auth/passwordChange";
import type { PageLoad } from "./$types";

export const load: PageLoad = async (event) => {
  const { eneo } = await event.parent();

  // Stable dependency key for manual invalidation after mutations
  event.depends("admin:users");

  // Read search, tab, and page parameters from URL for server-side filtering.
  // Support both canonical `search` and legacy `search_email` links.
  const search_email =
    event.url.searchParams.get("search") || event.url.searchParams.get("search_email") || undefined;
  const tab = event.url.searchParams.get("tab") || "active"; // Default to 'active' tab
  const page = parseInt(event.url.searchParams.get("page") || "1", 10) || 1;

  // Convert tab to state_filter for backend
  // 'active' tab shows ACTIVE + INVITED users (users who can log in)
  // 'inactive' tab shows INACTIVE users (temporary leave)
  const state_filter = tab === "inactive" ? "inactive" : "active";

  // Backend now returns { items: User[], metadata: PaginationMetadata }
  const [response, passwordPolicy] = await Promise.all([
    eneo.users.list({
      includeDetails: true,
      search_email, // Server-side search
      state_filter, // Server-side state filtering
      page // Server-side pagination
    }),
    eneo.users.passwordPolicy()
  ]);
  const passwordCapability = normalizeLocalPasswordCapability(passwordPolicy);
  if (passwordCapability.source !== "eneo") {
    error(503, { status: 503, code: 0, message: m.password_policy_unavailable() });
  }

  // Extract items, pagination, and state counts from response
  const users = response.items || [];
  const pagination =
    ((response as unknown as Record<string, unknown>).metadata as {
      page: number;
      total_pages: number;
      total_count: number;
      page_size: number;
      has_next: boolean;
      has_previous: boolean;
    } | null) ?? null;
  const counts =
    ((
      (response as unknown as Record<string, unknown>).metadata as
        Record<string, unknown> | undefined
    )?.counts as { active?: number; inactive?: number } | null) ?? null;

  return {
    passwordCapability,
    users,
    pagination,
    counts // State counts for tab display (active, inactive)
  };
};
