"use client";

import { Check } from "lucide-react";
import { useTranslations } from "next-intl";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

// Split contexts so sections (which only set) don't re-render on every count change.
const SetDirtyContext = createContext<((key: string, dirty: boolean) => void) | null>(null);
const DirtyKeysContext = createContext<readonly string[]>([]);

/**
 * Aggregates per-section unsaved state. The editor saves per section, so this
 * only powers the header indicator — it never blocks or batch-saves.
 */
export function SaveStatusProvider({ children }: { children: React.ReactNode }) {
  const [dirtyKeys, setDirtyKeys] = useState<readonly string[]>([]);

  const setDirty = useCallback((key: string, dirty: boolean) => {
    setDirtyKeys((current) => {
      const has = current.includes(key);
      if (dirty === has) return current;
      return dirty ? [...current, key] : current.filter((other) => other !== key);
    });
  }, []);

  return (
    <SetDirtyContext.Provider value={setDirty}>
      <DirtyKeysContext.Provider value={dirtyKeys}>{children}</DirtyKeysContext.Provider>
    </SetDirtyContext.Provider>
  );
}

/** Report a section's unsaved state to the header indicator. No-op outside a provider. */
export function useReportDirty(key: string, dirty: boolean) {
  const setDirty = useContext(SetDirtyContext);
  useEffect(() => {
    setDirty?.(key, dirty);
    return () => setDirty?.(key, false);
  }, [setDirty, key, dirty]);
}

/**
 * Header chip: "All changes saved", or a link to the first section with unsaved
 * changes (`href="#<sectionId>"`, matching the section anchor ids).
 */
export function SaveStatusIndicator() {
  const t = useTranslations();
  const dirtyKeys = useContext(DirtyKeysContext);
  const count = dirtyKeys.length;
  const label = useMemo(
    () => (count > 0 ? t("unsaved_changes", { count }) : t("all_changes_saved")),
    [count, t]
  );

  if (count > 0) {
    return (
      <a
        href={`#${dirtyKeys[0]}`}
        aria-live="polite"
        className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 text-sm transition-colors"
      >
        <span aria-hidden="true" className="size-2 rounded-full bg-amber-500" />
        {label}
      </a>
    );
  }

  return (
    <span
      aria-live="polite"
      className="text-muted-foreground inline-flex items-center gap-1.5 text-sm"
    >
      <Check aria-hidden="true" className="size-3.5" />
      {label}
    </span>
  );
}
