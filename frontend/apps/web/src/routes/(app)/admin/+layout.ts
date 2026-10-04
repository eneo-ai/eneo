/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { hasPermission } from "$lib/core/hasPermission.js";
import {
  RETENTION_ONLY_ADMIN_HREF,
  canOpenAdmin,
  retentionAccess,
  retentionOnlyAllows
} from "$lib/features/flows/retentionAccess";
import { deLocalizeHref, localizeHref } from "$lib/paraglide/runtime";
import { redirect } from "@sveltejs/kit";

export const load = async (event) => {
  event.depends("admin:layout");

  const { user, eneo } = await event.parent();

  // This check potentially runs client side, so this is _not_ a security feature
  // The actual security is on the backend, where all org calls will fail if not superuser
  const access = retentionAccess(hasPermission(user));
  if (!canOpenAdmin(access)) {
    redirect(302, "/");
  }
  // A retention-only role (retention_manage / retention_holds without admin)
  // works in the retention part of Flow settings and nowhere else here.
  if (!access.admin) {
    if (!retentionOnlyAllows(event.url, deLocalizeHref(event.url.pathname))) {
      redirect(302, localizeHref(RETENTION_ONLY_ADMIN_HREF));
    }
    return { auditConfig: null, settings: await eneo.settings.get() };
  }

  const [auditConfig, settings] = await Promise.all([eneo.audit.getConfig(), eneo.settings.get()]);

  return {
    auditConfig,
    settings
  };
};
