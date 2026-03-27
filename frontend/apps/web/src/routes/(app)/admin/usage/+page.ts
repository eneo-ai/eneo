/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { CalendarDate } from "@internationalized/date";

export const load = async (event) => {
  const { eneo } = await event.parent();

  const now = new Date();
  const today = new CalendarDate(now.getFullYear(), now.getMonth() + 1, now.getDate());
  const dateRange = {
    startDate: today.subtract({ days: 30 }).toString(),
    // We add one day so the end day includes the whole day. otherwise this would be interpreted as 00:00
    endDate: today.add({ days: 1 }).toString()
  };

  const [spaces, storageStats, tokenStats] = await Promise.all([
    eneo.usage.storage.listSpaces().then((s) => s.sort((a, b) => b.size - a.size)),
    eneo.usage.storage.getSummary(),
    eneo.usage.tokens.getSummary(dateRange)
  ]);

  return { spaces, storageStats, tokenStats };
};
