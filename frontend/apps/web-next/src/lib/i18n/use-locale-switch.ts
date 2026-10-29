"use client";

import { useRouter } from "@/lib/navigation";
import { useLocale, useTranslations } from "use-intl";
import { useOptimistic, useTransition } from "react";
import { useSetLocale } from "@/components/providers/intl-provider";
import { toastApiError } from "@/lib/api/toast";
import { isLocale } from "./locales";

/**
 * Marks a language immediately while its catalogue loads. A failed load
 * restores the picker; a choice while one is under way is ignored.
 */
export function useLocaleSwitch() {
  const t = useTranslations();
  const router = useRouter();
  const setLocale = useSetLocale();
  const [isSwitching, startTransition] = useTransition();
  const [locale, showLocale] = useOptimistic(useLocale());

  function switchLocale(next: string) {
    if (!isLocale(next) || isSwitching || next === locale) return;
    startTransition(async () => {
      showLocale(next);
      try {
        await setLocale(next);
        // Refresh remaining server-rendered routes through the navigation seam.
        router.refresh();
      } catch (error) {
        toastApiError(error, t);
      }
    });
  }
  return { locale, switchLocale };
}
