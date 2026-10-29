"use client";

import { useLocale } from "use-intl";
import { switchLocale } from "./switch-locale";

/** Pickers share the document's locale and its single persistence/navigation owner. */
export function useLocaleSwitch() {
  const locale = useLocale();
  return {
    locale,
    switchLocale(next: string) {
      if (next !== locale) switchLocale(next);
    }
  };
}
