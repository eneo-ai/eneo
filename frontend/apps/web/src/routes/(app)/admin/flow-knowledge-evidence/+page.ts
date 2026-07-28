export const load = async (event) => {
  const { eneo } = await event.parent();
  const ragEvidencePolicy = await eneo.settings.getRagEvidencePolicy();
  return { ragEvidencePolicy };
};
