"use client";

import { Check, CircleAlert, Loader2, OctagonX } from "lucide-react";
import { useTranslations } from "next-intl";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { useBeforeUnloadWarning } from "@/lib/hooks/use-before-unload-warning";

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
  useBeforeUnloadWarning(guarded);

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

type IndicatorState = "error" | "saving" | "dirty" | "saved";

/**
 * Header chip reflecting the aggregate save state: an error (linking to the
 * field that failed) wins over an in-flight save, which wins over dirty local
 * drafts, which wins over the resting "all saved" state. `aria-live` announces
 * transitions to screen readers. When a save lands, the check mark pops in
 * once (tw-animate-css; the global reduced-motion rule turns it off), so the
 * flip from "Sparar…" to "Alla ändringar sparade" is seen, not just read.
 */
export function SaveStatusIndicator() {
  const t = useTranslations();
  const statuses = useContext(StatusMapContext);
  const keys = Object.keys(statuses);
  const errorKey = keys.find((key) => statuses[key] === "error");
  const saving = keys.some((key) => statuses[key] === "saving");
  const dirtyCount = keys.filter((key) => statuses[key] === "dirty").length;
  const state: IndicatorState = errorKey
    ? "error"
    : saving
      ? "saving"
      : dirtyCount
        ? "dirty"
        : "saved";

  // The check animates only when a save just landed, not on first render:
  // remember the previous state and count the landings (state adjusted during
  // render, React's pattern for deriving from a change), so each landing
  // restarts the animation (the key changes) while the resting state stays
  // still.
  const [previous, setPrevious] = useState(state);
  const [landings, setLandings] = useState(0);
  if (previous !== state) {
    setPrevious(state);
    if (state === "saved" && previous === "saving") setLandings(landings + 1);
  }
  const justSaved = state === "saved" && landings > 0;

  // Saved and failed are announced once each through the shared live region
  // (ACCESSIBILITY.md → status messages); the visible text itself is not live,
  // so "Sparar…" and the unsaved count never chatter.
  const announce = useAnnounce();
  useEffect(() => {
    if (justSaved) announce(t("all_changes_saved"));
  }, [justSaved, landings, announce, t]);
  useEffect(() => {
    if (errorKey) announce(t("save_failed"));
  }, [errorKey, announce, t]);

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
        <Check
          key={landings}
          aria-hidden="true"
          data-just-saved={justSaved || undefined}
          className={justSaved ? "animate-in fade-in zoom-in-50 size-3.5 duration-300" : "size-3.5"}
        />
        {t("all_changes_saved")}
      </span>
    );
  }

  return <span>{content}</span>;
}
