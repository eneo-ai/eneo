/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/
import { redirect } from "@sveltejs/kit";

export const load = async (event) => {
  const { intric, user } = await event.parent();

  const hasSharedSpaces = user?.roles?.some((role) => role.permissions?.includes("shared_spaces"));

  // Personal-space routes live outside the shared_spaces gate.
  // Everything else under /spaces/** requires the permission.
  // We redirect instead of throwing 403 so mid-session revocations and
  // external deep-links (SSO returns, email) land users somewhere useful
  // with a toast explaining why they were moved.
  const isPersonalRoute = event.url.pathname.startsWith("/spaces/personal");
  const isOrganizationRoute = event.url.pathname.startsWith("/spaces/organization");
  if (!hasSharedSpaces && !isPersonalRoute && !isOrganizationRoute) {
    redirect(302, "/spaces/personal/chat?blocked=shared_spaces");
  }

  // Only fetch org space if user has admin permission
  const orgPromise = user?.roles?.some((role) => role.permissions?.includes("admin"))
    ? intric.spaces.getOrganizationSpace().catch((e) => {
        if (e?.status === 403 || e?.response?.status === 403) return null;
        throw e;
      })
    : Promise.resolve(null);

  const [spaces, currentSpace, organizationSpace] = await Promise.all([
    intric.spaces.list(),
    intric.spaces.getPersonalSpace(),
    orgPromise
  ]);

  return {
    spaces,
    currentSpace,
    organizationSpace,
    loadedAt: new Date().toUTCString()
  };
};
