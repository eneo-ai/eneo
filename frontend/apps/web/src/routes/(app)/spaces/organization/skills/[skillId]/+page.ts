export const load = async (event) => {
  event.depends("organization:skills");
  const { eneo } = await event.parent();
  const skillId = event.params.skillId;

  const skillPromise = eneo.skills.organization.get({ skillId });
  const revisionPagePromise = eneo.skills.organization.listRevisionSummaries({ skillId });
  const adoptionPage = eneo.skills.organization.getAdoption({ skillId });
  // Mark the streamed promise handled before other loader work completes.
  // The page's await block still receives the original rejection.
  adoptionPage.catch(() => {});
  const skill = await skillPromise;
  const [revisionPage, published] = await Promise.all([
    revisionPagePromise,
    skill.published_revision_number === null
      ? Promise.resolve(null)
      : eneo.skills.catalogue.get({ skillId })
  ]);
  return {
    skill,
    revisionPage,
    published,
    adoptionPage
  };
};
