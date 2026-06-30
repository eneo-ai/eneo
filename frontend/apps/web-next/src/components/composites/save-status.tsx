"use client";

import { Check } from "lucide-react";
import { useTranslations } from "next-intl";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

// Split contexts so sections (which only set) don't re-render on every count change.
const SetDirtyContext = createContext<((key: string, dirty: boolean) => void) | null>(null);
const DirtyCountContext = createContext(0);

/**
 * Aggregates per-section unsaved state. The editor saves per section, so this
 * only powers the header indicator — it never blocks or batch-saves.
 */
export function SaveStatusProvider({ children }: { children: React.ReactNode }) {
  const [dirtyKeys, setDirtyKeys] = useState<ReadonlySet<string>>(() => new Set());

  const setDirty = useCallback((key: string, dirty: boolean) => {
    setDirtyKeys((current) => {
      if (dirty === current.has(key)) return current;
      const next = new Set(current);
      if (dirty) next.add(key);
      else next.delete(key);
      return next;
    });
  }, []);

  return (
    <SetDirtyContext.Provider value={setDirty}>
      <DirtyCountContext.Provider value={dirtyKeys.size}>{children}</DirtyCountContext.Provider>
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

/** Header chip: "All changes saved" or "N unsaved changes". */
export function SaveStatusIndicator() {
  const t = useTranslations();
  const count = useContext(DirtyCountContext);
  const label = useMemo(
    () => (count > 0 ? t("unsaved_changes", { count }) : t("all_changes_saved")),
    [count, t]
  );

  if (count > 0) {
    return (
      <span
        aria-live="polite"
        className="text-muted-foreground inline-flex items-center gap-1.5 text-sm"
      >
        <span aria-hidden="true" className="size-2 rounded-full bg-amber-500" />
        {label}
      </span>
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
