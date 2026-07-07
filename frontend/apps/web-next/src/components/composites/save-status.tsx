"use client";

import { Check, CircleAlert, Loader2, OctagonX } from "lucide-react";
import { useTranslations } from "next-intl";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

export type SaveStatus = "dirty" | "saving" | "error";

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
 * while there is dirty local state, an in-flight save, or a failed save.
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

  const guarded = useMemo(
    () => Object.values(statuses).some((status) => status !== null),
    [statuses]
  );

  // Catch full reloads / tab close while local state may not be durably saved.
  useEffect(() => {
    if (!guarded) return;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [guarded]);

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
 * field that failed) wins over an in-flight save, which wins over dirty local
 * drafts, which wins over the resting "all saved" state. `aria-live` announces
 * transitions to screen readers.
 */
export function SaveStatusIndicator() {
  const t = useTranslations();
  const statuses = useContext(StatusMapContext);
  const keys = Object.keys(statuses);
  const errorKey = keys.find((key) => statuses[key] === "error");
  const saving = keys.some((key) => statuses[key] === "saving");
  const dirtyCount = keys.filter((key) => statuses[key] === "dirty").length;

  let content: React.ReactNode;
  if (errorKey) {
    content = (
      <a
        href={`#${errorKey}`}
        className="text-destructive inline-flex items-center gap-1.5 text-sm hover:underline"
      >
        <OctagonX aria-hidden="true" className="size-3.5" />
        {t("save_failed")}
      </a>
    );
  } else if (saving) {
    content = (
      <span className="text-muted-foreground inline-flex items-center gap-1.5 text-sm">
        <Loader2 aria-hidden="true" className="size-3.5 animate-spin" />
        {t("saving")}
      </span>
    );
  } else if (dirtyCount > 0) {
    content = (
      <span className="text-muted-foreground inline-flex items-center gap-1.5 text-sm">
        <CircleAlert aria-hidden="true" className="size-3.5" />
        {t("unsaved_changes", { count: dirtyCount })}
      </span>
    );
  } else {
    content = (
      <span className="text-muted-foreground inline-flex items-center gap-1.5 text-sm">
        <Check aria-hidden="true" className="size-3.5" />
        {t("all_changes_saved")}
      </span>
    );
  }

  return (
    <span aria-live="polite" role="status">
      {content}
    </span>
  );
}
