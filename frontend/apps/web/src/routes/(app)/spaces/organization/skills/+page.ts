export const load = async (event) => {
  event.depends("organization:skills");
  const { eneo } = await event.parent();
  const search = event.url.searchParams.get("search")?.trim() ?? "";
  const removed = event.url.searchParams.get("removed") === "true";
  const page = await eneo.skills.organization.list({
    search: search || undefined,
    removed
  });
  return {
    page,
    search,
    removed
  };
};
