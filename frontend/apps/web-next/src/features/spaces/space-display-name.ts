import { useTranslations } from "use-intl";
import { useSpace } from "./use-space";

/** The space's display name: personal and organization spaces use their alias. */
export function useSpaceDisplayName(): string {
  const t = useTranslations();
  const { space } = useSpace();
  if (space.personal) return t("personal");
  if (space.organization) return t("organization");
  return space.name;
}
