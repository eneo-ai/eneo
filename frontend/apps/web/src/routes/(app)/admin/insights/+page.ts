/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

export const load = async (event) => {
  const { eneo } = await event.parent();

  event.depends("insights:list");

  const now = new Date();

  const timeframe = {
    start: new Date(now.setDate(now.getDate() - 30)).toISOString(),
    end: new Date().toISOString()
  };

  return {
    data: eneo.analytics.getAggregated(timeframe),
    timeframe
  };
};
