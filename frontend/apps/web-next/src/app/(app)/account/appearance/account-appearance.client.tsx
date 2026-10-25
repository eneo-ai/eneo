"use client";

import { Icon } from "@astryxdesign/core/Icon";
import { RadioList, RadioListItem } from "@astryxdesign/core/RadioList";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { useLocale, useTranslations } from "next-intl";
import { useTheme } from "next-themes";
import { useEffect, useId, useRef } from "react";
import { THEMES } from "@/components/shell/theme-switcher";
import { useHydrated } from "@/lib/hooks/use-hydrated";
import { LOCALE_LABELS, locales } from "@/lib/i18n/locales";
import { useLocaleSwitch } from "@/lib/i18n/use-locale-switch";

/**
 * "Utseende och språk", pushed from Konto: both choices in view at once, each
 * applied as it is made and said politely ("Tema: Mörkt"), so nothing waits
 * for a save. A new language is said once the page is in it.
 */
export function AccountAppearance() {
  const t = useTranslations();
  const { theme, setTheme } = useTheme();
  const hydrated = useHydrated();
  const pageLocale = useLocale();
  const { locale, switchLocale } = useLocaleSwitch();
  const announce = useAnnounce();
  const themeId = useId();
  const languageId = useId();

  const say = (setting: string, value: string) =>
    announce(t("account_choice_announced", { setting, value }));

  // The language chosen here, said when the page arrives in it ("Language: English").
  const chosenLocale = useRef<string | null>(null);
  useEffect(() => {
    if (chosenLocale.current !== pageLocale) return;
    chosenLocale.current = null;
    announce(
      t("account_choice_announced", {
        setting: t("language"),
        value: LOCALE_LABELS[pageLocale] ?? pageLocale
      })
    );
  }, [announce, pageLocale, t]);

  return (
    // The width of a phone's, beside the SideNav too.
    <div className="flex flex-col gap-8 lg:max-w-md">
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <h2 id={themeId} className="text-[1.0625rem] font-semibold">
            {t("theme")}
          </h2>
          <p className="text-ax-text-secondary text-sm text-pretty">
            {t("account_theme_system_hint")}
          </p>
        </div>
        {/* next-themes knows the theme only in the browser: none is marked until then. */}
        <SegmentedControl
          label={t("theme")}
          value={hydrated ? (theme ?? "system") : ""}
          onChange={(next) => {
            setTheme(next);
            const option = THEMES.find(({ value }) => value === next);
            if (option) say(t("theme"), t(option.labelKey));
          }}
          layout="fill"
          size="lg"
        >
          {THEMES.map(({ value, labelKey, icon }) => (
            <SegmentedControlItem
              key={value}
              value={value}
              label={t(labelKey)}
              icon={<Icon icon={icon} />}
            />
          ))}
        </SegmentedControl>
      </div>
      <div className="flex flex-col gap-1">
        <h2 id={languageId} className="text-[1.0625rem] font-semibold">
          {t("language")}
        </h2>
        <RadioList
          label={t("language")}
          isLabelHidden
          value={locale}
          onChange={(next) => {
            chosenLocale.current = next;
            switchLocale(next);
          }}
        >
          {locales.map((value) => (
            <RadioListItem
              key={value}
              value={value}
              // Each in its own language, marked with `lang` (WCAG 3.1.2).
              label={<span lang={value}>{LOCALE_LABELS[value] ?? value}</span>}
            />
          ))}
        </RadioList>
      </div>
    </div>
  );
}
