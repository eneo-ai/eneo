"use client";

import { replaceUrl, useSearchParams } from "@/lib/navigation";
import { useCallback } from "react";

/**
 * A tab selection mirrored in `?tab=` so a tab can be linked to and survives
 * a reload, without adding history entries for every click. The fallback
 * tab keeps the URL clean.
 */
export function useUrlTab<Tab extends string>(
  tabs: readonly Tab[],
  fallback: Tab
): [Tab, (tab: Tab) => void] {
  const params = useSearchParams();
  const initial = params.get("tab");
  const tab = tabs.includes(initial as Tab) ? (initial as Tab) : fallback;
  const select = useCallback(
    (next: Tab) => {
      const url = new URL(window.location.href);
      if (next === fallback) url.searchParams.delete("tab");
      else url.searchParams.set("tab", next);
      replaceUrl(url, { ignoreBlocker: true });
    },
    [fallback]
  );
  return [tab, select];
}
