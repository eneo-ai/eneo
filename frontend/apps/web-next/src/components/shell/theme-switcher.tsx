"use client";

import { Moon, Sun } from "lucide-react";
import { useTranslations } from "next-intl";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { useHydrated } from "@/lib/hooks/use-hydrated";

export function ThemeSwitcher() {
  const t = useTranslations();
  const { theme, resolvedTheme, setTheme } = useTheme();
  // resolvedTheme is only known on the client; render the server's icon until
  // hydrated so the trigger never mismatches.
  const hydrated = useHydrated();
  const ThemeIcon = hydrated && resolvedTheme === "dark" ? Moon : Sun;
  const themes = [
    { value: "light", label: t("light") },
    { value: "dark", label: t("dark") },
    { value: "system", label: t("system") }
  ];

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon">
          <ThemeIcon className="size-4" />
          <span className="sr-only">{t("theme")}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {/* Radio items expose the current choice to screen readers
            (menuitemradio + aria-checked) and mark it visibly. */}
        <DropdownMenuRadioGroup value={theme} onValueChange={setTheme}>
          {themes.map(({ value, label }) => (
            <DropdownMenuRadioItem key={value} value={value}>
              {label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
