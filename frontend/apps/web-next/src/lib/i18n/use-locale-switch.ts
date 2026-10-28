"use client";

import { useRouter } from "@/lib/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useOptimistic, useTransition } from "react";
import { toastApiError } from "@/lib/api/toast";
import { setLocale } from "./actions";

/**
 * Switches the language: the NEXT_LOCALE cookie (read by request.ts), then
 * the page again in the new language. `locale` is the chosen one from the
 * moment it is chosen (a picker marks it at once, and goes back if saving
 * fails); a choice while one is under way is ignored.
 */
export function useLocaleSwitch() {
  const t = useTranslations();
  const router = useRouter();
  const [isSwitching, startTransition] = useTransition();
  const [locale, showLocale] = useOptimistic(useLocale());

  function switchLocale(next: string) {
    if (isSwitching || next === locale) return;
    startTransition(async () => {
      showLocale(next);
      try {
        await setLocale(next);
        router.refresh();
      } catch (error) {
        toastApiError(error, t);
      }
    });
  }
  return { locale, switchLocale };
}
