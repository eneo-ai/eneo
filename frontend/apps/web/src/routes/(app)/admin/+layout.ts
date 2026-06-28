/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { hasPermission } from "$lib/core/hasPermission.js";
import { redirect } from "@sveltejs/kit";

export const load = async (event) => {
  event.depends("admin:layout");

  const { user, eneo } = await event.parent();

  // This check potentially runs client side, so this is _not_ a security feature
  // The actual security is on the backend, where all org calls will fail if not superuser
  if (!hasPermission(user)("admin")) {
    redirect(302, "/");
  }

  const [auditConfig, settings] = await Promise.all([eneo.audit.getConfig(), eneo.settings.get()]);

  return {
    auditConfig,
    settings
  };
};
