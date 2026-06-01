/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { CalendarDate } from "@internationalized/date";

export const load = async (event) => {
  const { intric } = await event.parent();

  const now = new Date();
  const today = new CalendarDate(now.getFullYear(), now.getMonth() + 1, now.getDate());
  const dateRange = {
    startDate: today.subtract({ days: 30 }).toString(),
    // We add one day so the end day includes the whole day. otherwise this would be interpreted as 00:00
    endDate: today.add({ days: 1 }).toString()
  };

  // We pull the model list alongside the token stats so the per-row "estimated
  // cost" column can apply the current ratecard without a second round-trip.
  // The mapping is `model_id → { input_cost_per_token, output_cost_per_token }`,
  // built once on the page since both TokenOverviewTable and UserTokenTable
  // consume it.
  const [spaces, storageStats, tokenStats, models] = await Promise.all([
    intric.usage.storage.listSpaces().then((s) => s.sort((a, b) => b.size - a.size)),
    intric.usage.storage.getSummary(),
    intric.usage.tokens.getSummary(dateRange),
    intric.models.list()
  ]);

  return { spaces, storageStats, tokenStats, models };
};
