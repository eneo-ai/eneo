/*
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { hasPermission } from "$lib/core/hasPermission.js";
import { redirect } from "@sveltejs/kit";

export const load = async (event) => {
  event.depends("admin:personal-assistant");
  const { user } = await event.parent();
  if (!hasPermission(user)("admin")) {
    redirect(302, "/");
  }
  return {};
};
