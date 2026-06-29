/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/
type UserRole = {
  permissions?: string[];
};

type UserWithRoles = {
  roles?: UserRole[];
} | null;

function isAdminUser(user: UserWithRoles | undefined) {
  return user?.roles?.some((role: UserRole) => role.permissions?.includes("admin")) ?? false;
}

export const load = async (event) => {
  const { intric, user } = await event.parent();

  // Only fetch org space if user has admin permission
  const orgPromise = isAdminUser(user)
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
