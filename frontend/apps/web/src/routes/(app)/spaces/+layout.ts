/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

export const load = async (event) => {
  const { intric } = await event.parent();

  const orgPromise = intric.spaces
    .getOrganizationSpace()
    .catch((e) => {
      if (e?.status === 403 || e?.response?.status === 403) return null;
      throw e;
    });

  const [spaces, currentSpace, organizationSpace] = await Promise.all([
    intric.spaces.list(),
    intric.spaces.getPersonalSpace(),
    orgPromise,
  ]);

  return {
    spaces,
    currentSpace,
    organizationSpace, 
    loadedAt: new Date().toUTCString(),
  };
};