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

  const [assistants, spaces] = await Promise.all([
    intric.assistants.list(),
    intric.spaces.list()
  ]);

  const spaceNameById = new Map(spaces.map((space) => [space.id, space.name]));

  const assistantsWithSpace = assistants.map((assistant) => {
    const resolvedSpaceName = spaceNameById.get(assistant.space_id);
    const hasSpaceName = Boolean(resolvedSpaceName);
    return {
      ...assistant,
      space_name: resolvedSpaceName ?? "—",
      space_short_id: assistant.space_id?.slice(0, 8) ?? "",
      has_space_name: hasSpaceName
    };
  });

  return {
    assistants: assistantsWithSpace,
    data: intric.analytics.getAggregated(timeframe),
    timeframe
  };
};
