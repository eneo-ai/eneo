export const load = async (event) => {
  event.depends("organization:skills");
  const { eneo } = await event.parent();
  const skillId = event.params.skillId;

  const skillPromise = eneo.skills.organization.get({ skillId });
  const revisionPagePromise = eneo.skills.organization.listRevisionSummaries({ skillId });
  const adoptionPage = eneo.skills.organization.getAdoption({ skillId });
  const executionBlockPromise = eneo.settings.getSkillExecutionBlock({ skillId });
  // Both requests can settle before the Skill lookup. Keep their original
  // rejections observable while preventing transient unhandled rejections.
  revisionPagePromise.catch(() => {});
  adoptionPage.catch(() => {});
  executionBlockPromise.catch(() => {});
  const skill = await skillPromise;
  const [revisionPage, published, executionBlock] = await Promise.all([
    revisionPagePromise,
    skill.published_revision_number === null
      ? Promise.resolve(null)
      : eneo.skills.catalogue.get({ skillId }),
    executionBlockPromise
  ]);
  return {
    skill,
    revisionPage,
    published,
    adoptionPage,
    executionBlock
  };
};
