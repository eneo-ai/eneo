export const load = async (event) => {
  event.depends("organization:skills");
  const { eneo } = await event.parent();
  const search = event.url.searchParams.get("search")?.trim() ?? "";
  const page = await eneo.skills.organization.list({
    search: search || undefined
  });
  return {
    page,
    search
  };
};
