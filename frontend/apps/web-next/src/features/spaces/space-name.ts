/**
 * The name a space is shown by. The backend names the personal and the
 * organisation space in English ("Organization space"); the UI shows its
 * own translated names for them and the user's name for every other space.
 */
export function spaceDisplayName(
  space: { name: string; personal: boolean; organization: boolean },
  t: (key: "personal" | "organization_space") => string
): string {
  if (space.personal) return t("personal");
  if (space.organization) return t("organization_space");
  return space.name;
}
