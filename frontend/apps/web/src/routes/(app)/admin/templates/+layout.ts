/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { hasPermission } from "$lib/core/hasPermission.js";
import { redirect } from "@sveltejs/kit";

export const load = async (event) => {
  const { user, settings } = await event.parent();

  // Check admin permission
  if (!hasPermission(user)("admin")) {
    throw redirect(302, "/admin");
  }

  // Check feature flag enabled
  if (!settings.using_templates) {
    throw redirect(302, "/admin");
  }

  return {};
};
