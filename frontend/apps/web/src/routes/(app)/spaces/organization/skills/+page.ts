export const load = async (event) => {
  event.depends("organization:skills");
  const { eneo, canManage } = await event.parent();
  const search = event.url.searchParams.get("search")?.trim() ?? "";

  if (canManage) {
    const page = await eneo.skills.organization.list({
      search: search || undefined
    });
    return {
      mode: "manage" as const,
      page,
      search
    };
  }

  const page = await eneo.skills.catalogue.list({
    search: search || undefined
  });
  return {
    mode: "browse" as const,
    page,
    search
  };
};
