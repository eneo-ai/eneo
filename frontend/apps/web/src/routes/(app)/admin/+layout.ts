/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { hasPermission } from "$lib/core/hasPermission.js";
import { CalendarDate } from "@internationalized/date";
import { redirect } from "@sveltejs/kit";

export const load = async (event) => {
  event.depends("admin:layout");

  const { user, intric } = await event.parent();

  // This check potentially runs client side, so this is _not_ a security feature
  // The actual security is on the backend, where all org calls will fail if not superuser
  if (!hasPermission(user)("admin")) {
    redirect(302, "/");
  }

  const now = new Date();
  const today = new CalendarDate(now.getFullYear(), now.getMonth() + 1, now.getUTCDate());
  const dateRange = {
    startDate: today.subtract({ days: 30 }).toString(),
    // We add one day so the end day includes the whole day. otherwise this would be interpreted as 00:00
    endDate: today.add({ days: 1 }).toString()
  };

  const [storageStats, tokenStats, auditConfig, settings] = await Promise.all([
    intric.usage.storage.getSummary(),
    intric.usage.tokens.getSummary(dateRange),
    intric.audit.getConfig(),
    intric.settings.get()
  ]);

  return {
    storageStats,
    tokenStats,
    auditConfig,
    settings
  };
};
