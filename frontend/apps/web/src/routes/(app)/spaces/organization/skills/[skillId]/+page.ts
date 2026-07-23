export const load = async (event) => {
  event.depends("organization:skills");
  const { eneo } = await event.parent();
  const skillId = event.params.skillId;

  const skill = await eneo.skills.organization.get({ skillId });
  const [revisionPage, published] = await Promise.all([
    eneo.skills.organization.listRevisionSummaries({ skillId }),
    skill.published_revision_number === null
      ? Promise.resolve(null)
      : eneo.skills.catalogue.get({ skillId })
  ]);
  return {
    skill,
    revisionPage,
    published
  };
};
