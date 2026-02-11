/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { CalendarDate } from "@internationalized/date";
import { parseDate } from "@internationalized/date";
import type { Assistant } from "@intric/intric-js";

export const load = async (event) => {
  const { intric } = await event.parent();

  event.depends("insights:assistant");

  const id = event.params.assistantId;
  const searchParams = event.url.searchParams;
  const now = new Date();
  const today = new CalendarDate(
    now.getFullYear(),
    now.getMonth() + 1,
    now.getUTCDate()
  );
  const defaultStart = today.subtract({ days: 30 });

  const fromQuery = searchParams.get("from");
  const toQuery = searchParams.get("to");
  const followupsQuery = searchParams.get("followups");

  const includeFollowups =
    followupsQuery === null ? true : followupsQuery === "true";

  const start = (() => {
    if (!fromQuery) return defaultStart;
    try {
      return parseDate(fromQuery);
    } catch {
      return defaultStart;
    }
  })();

  const end = (() => {
    if (!toQuery) return today;
    try {
      return parseDate(toQuery);
    } catch {
      return today;
    }
  })();

  const assistant: Assistant = await intric.assistants.get({ id });

  return {
    assistant,
    timeframe: {
      start,
      end
    },
    includeFollowups
  };
};
