"use client";

import {
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSubMenu
} from "@astryxdesign/core/DropdownMenu";
import { Monitor, Moon, Sun, SunMoon } from "lucide-react";
import { useTranslations } from "next-intl";
import { useTheme } from "next-themes";

const THEMES = [
  { value: "light", labelKey: "light", icon: Sun },
  { value: "dark", labelKey: "dark", icon: Moon },
  { value: "system", labelKey: "system", icon: Monitor }
] as const;

/**
 * Colour-mode choice inside the profile menu: a "Tema" submenu of radio items,
 * so the current mode is announced (menuitemradio + aria-checked) and marked.
 * next-themes owns the mode (see AGENTS.md → Colour mode).
 */
export function ThemeSubMenu() {
  const t = useTranslations();
  const { theme, setTheme } = useTheme();

  return (
    <DropdownMenuSubMenu icon={SunMoon} label={t("theme")}>
      <DropdownMenuRadioGroup label={t("theme")} value={theme} onChange={setTheme}>
        {THEMES.map(({ value, labelKey, icon }) => (
          <DropdownMenuRadioItem key={value} value={value} icon={icon} label={t(labelKey)} />
        ))}
      </DropdownMenuRadioGroup>
    </DropdownMenuSubMenu>
  );
}
