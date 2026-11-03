import { useTheme } from "next-themes";

/** The signed-in app's current scheme, including its system preference. */
export function useAppScheme(): "light" | "dark" {
  const { resolvedTheme } = useTheme();
  return resolvedTheme === "dark" ? "dark" : "light";
}
