export const load = async (event) => {
  event.depends("organization:skills");
  const { eneo, canManage } = await event.parent();
  const skillId = event.params.skillId;

  if (!canManage) {
    const published = await eneo.skills.catalogue.get({ skillId });
    return {
      mode: "browse" as const,
      published
    };
  }

  const skill = await eneo.skills.organization.get({ skillId });
  const [revisionPage, published] = await Promise.all([
    eneo.skills.organization.listRevisionSummaries({ skillId }),
    skill.published_revision_number === null
      ? Promise.resolve(null)
      : eneo.skills.catalogue.get({ skillId })
  ]);
  return {
    mode: "manage" as const,
    skill,
    revisionPage,
    published
  };
};
