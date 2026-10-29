"use client";

import { useAppContext } from "@/components/providers/app-context";
import { useSpace } from "@/features/spaces/use-space";

/**
 * Attaching Skills to Assistants and Apps needs Use Skills ("skills"). Own
 * Skills ("personal_skills") opens the personal-space library and the
 * personal chat only, so library read access alone does not show the picker.
 */
export function useCanAttachSkills(): boolean {
  const { can: spaceAllows } = useSpace();
  const { can: userHas } = useAppContext();
  return spaceAllows("read", "skill") && userHas("skills");
}
