"use client";

import { Check, Loader2, OctagonX } from "lucide-react";
import { useTranslations } from "next-intl";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

export type SaveStatus = "saving" | "error";

// Split contexts so callers that only set status don't re-render on every map
// change. The map drives the header indicator and the unsaved-changes guard.
const SetStatusContext = createContext<((key: string, status: SaveStatus | null) => void) | null>(
  null
);
const StatusMapContext = createContext<Readonly<Record<string, SaveStatus>>>({});

/**
 * Aggregates the live save status of every autosaving field on the page. Pages
 * autosave per field, so this powers two things: the header indicator
 * (Saving… / All saved / Couldn't save) and a beforeunload guard that warns
 * only while a save is actually in flight — there is no "unsaved draft" to lose.
 */
export function SaveStatusProvider({ children }: { children: React.ReactNode }) {
  const [statuses, setStatuses] = useState<Record<string, SaveStatus>>({});

  const setStatus = useCallback((key: string, status: SaveStatus | null) => {
    setStatuses((current) => {
      if (status === null) {
        if (!(key in current)) return current;
        const next = { ...current };
        delete next[key];
        return next;
      }
      if (current[key] === status) return current;
      return { ...current, [key]: status };
    });
  }, []);

  const saving = useMemo(
    () => Object.values(statuses).some((status) => status === "saving"),
    [statuses]
  );

  // Catch full reloads / tab close during the brief window a save is in flight.
  // In-app navigation keeps the mutation alive via react-query, so there is no
  // separate draft to guard.
  useEffect(() => {
    if (!saving) return;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [saving]);

  return (
    <SetStatusContext.Provider value={setStatus}>
      <StatusMapContext.Provider value={statuses}>{children}</StatusMapContext.Provider>
    </SetStatusContext.Provider>
  );
}

/** Report a field's save status to the header. Returns null outside a provider. */
export function useSetSaveStatus() {
  return useContext(SetStatusContext);
}

/**
 * Header chip reflecting the aggregate save state: an error (linking to the
 * field that failed) wins over an in-flight save, which wins over the resting
 * "all saved" state. `aria-live` announces transitions to screen readers.
 */
export function SaveStatusIndicator() {
  const t = useTranslations();
  const statuses = useContext(StatusMapContext);
  const keys = Object.keys(statuses);
  const errorKey = keys.find((key) => statuses[key] === "error");
  const saving = keys.some((key) => statuses[key] === "saving");

  if (errorKey) {
    return (
      <a
        href={`#${errorKey}`}
        aria-live="polite"
        className="text-destructive inline-flex items-center gap-1.5 text-sm hover:underline"
      >
        <OctagonX aria-hidden="true" className="size-3.5" />
        {t("save_failed")}
      </a>
    );
  }

  if (saving) {
    return (
      <span
        aria-live="polite"
        className="text-muted-foreground inline-flex items-center gap-1.5 text-sm"
      >
        <Loader2 aria-hidden="true" className="size-3.5 animate-spin" />
        {t("saving")}
      </span>
    );
  }

  return (
    <span
      aria-live="polite"
      className="text-muted-foreground inline-flex items-center gap-1.5 text-sm"
    >
      <Check aria-hidden="true" className="size-3.5" />
      {t("all_changes_saved")}
    </span>
  );
}
