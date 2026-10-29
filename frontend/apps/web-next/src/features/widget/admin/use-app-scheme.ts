"use client";

import { useTheme } from "next-themes";
import { useHydrated } from "@/lib/hooks/use-hydrated";

/**
 * The colour scheme the signed-in app is showing right now: the user's chosen
 * theme, resolved through the system setting when it is "system". Used so
 * previews and the in-app test follow what the admin sees, not the OS alone.
 * Light until hydrated, when next-themes knows.
 */
export function useAppScheme(): "light" | "dark" {
  const { resolvedTheme } = useTheme();
  const hydrated = useHydrated();
  return hydrated && resolvedTheme === "dark" ? "dark" : "light";
}
