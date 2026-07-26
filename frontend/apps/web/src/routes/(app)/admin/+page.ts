export const load = async (event) => {
  const { eneo } = await event.parent();
  const [skillRuntimePolicy, skillRuntimeModelProjections] = await Promise.all([
    eneo.settings.getSkillRuntimePolicy(),
    // The projection is explanatory; it must not make the settings page unavailable.
    eneo.settings.getSkillRuntimeModelProjections().catch(() => null)
  ]);

  return { skillRuntimePolicy, skillRuntimeModelProjections };
};
