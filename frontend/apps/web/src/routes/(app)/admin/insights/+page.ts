/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

export const load = async (event) => {
  const { intric } = await event.parent();

  event.depends("insights:list");

  const now = new Date();

  const timeframe = {
    start: new Date(now.setDate(now.getDate() - 30)).toISOString(),
    end: new Date().toISOString()
  };

  const [assistants] = await Promise.all([intric.assistants.list()]);

  return {
    assistants,
    data: intric.analytics.getAggregated(timeframe),
    timeframe
  };
};
