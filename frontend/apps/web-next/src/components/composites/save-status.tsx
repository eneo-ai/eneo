import { CircleAlert, Loader2, OctagonX } from "lucide-react";
import { SuccessMark } from "./success-mark";
import { useTranslations } from "use-intl";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { useBeforeUnloadWarning } from "@/lib/hooks/use-before-unload-warning";

export type SaveStatus = "dirty" | "saving" | "error";

/** A failed field saving again is not plain "saving": its link stays until the outcome is known. */
type TrackedStatus = SaveStatus | "retrying";

// Split contexts so callers that only set status don't re-render on every map
// change. The map drives the header indicator and the unsaved-changes guard.
const SetStatusContext = createContext<((key: string, status: SaveStatus | null) => void) | null>(
  null
);
const StatusMapContext = createContext<Readonly<Record<string, TrackedStatus>>>({});

/**
 * Aggregates the live save status of every autosaving field on the page. Pages
 * autosave per field, so this powers two things: the header indicator
 * (Saving… / All saved / Couldn't save) and a beforeunload guard that warns
 * while there is dirty local state, an in-flight save, or a failed save.
 */
export function SaveStatusProvider({ children }: { children: React.ReactNode }) {
  const [statuses, setStatuses] = useState<Record<string, TrackedStatus>>({});

  const setStatus = useCallback((key: string, status: SaveStatus | null) => {
    setStatuses((current) => {
      if (status === null) {
        if (!(key in current)) return current;
        const next = { ...current };
        delete next[key];
        return next;
      }
      const failedBefore = current[key] === "error" || current[key] === "retrying";
      const next = status === "saving" && failedBefore ? "retrying" : status;
      if (current[key] === next) return current;
      return { ...current, [key]: next };
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
 * transitions to screen readers. A failed field saving again keeps its link,
 * with a spinner: leaving the field to press that link is what starts the save,
 * and the link must not go from under the press or the keyboard's focus. When a
 * save lands, the check mark pops in once (tw-animate-css; the global
 * reduced-motion rule turns it off), so the flip from "Sparar…" to "Alla ändringar sparade" is seen, not just read.
 * A second copy shown where the first is hidden (an editor's phone views
 * beside its header) passes `isQuiet`, so each change is announced once;
 * `isCompact` says it in a word or two, for a phone's page bar.
 */
export function SaveStatusIndicator({
  isQuiet = false,
  isCompact = false,
  isHiddenWhenSaved = false
}: {
  isQuiet?: boolean;
  isCompact?: boolean;
  /** Says nothing while nothing is happening: for a place with no field of its own. */
  isHiddenWhenSaved?: boolean;
}) {
  const t = useTranslations();
  const statuses = useContext(StatusMapContext);
  const keys = Object.keys(statuses);
  const errorKey = keys.find((key) => statuses[key] === "error");
  const retryingKey = keys.find((key) => statuses[key] === "retrying");
  const linkKey = errorKey ?? retryingKey;
  const saving = retryingKey != null || keys.some((key) => statuses[key] === "saving");
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
    if (justSaved && !isQuiet) announce(t("all_changes_saved"));
  }, [justSaved, landings, announce, t, isQuiet]);
  useEffect(() => {
    if (errorKey && !isQuiet) announce(t("save_failed"));
  }, [errorKey, announce, t, isQuiet]);

  let content: React.ReactNode;
  if (linkKey) {
    content = (
      <a
        href={`#${linkKey}`}
        className="text-destructive inline-flex items-center gap-1.5 text-sm hover:underline pointer-coarse:min-h-11"
      >
        {errorKey ? (
          <OctagonX aria-hidden="true" className="size-3.5" />
        ) : (
          <Loader2 aria-hidden="true" className="size-3.5 animate-spin" />
        )}
        {t(isCompact ? "save_status_failed_short" : "save_failed")}
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
        {isCompact ? t("save_status_unsaved_short") : t("unsaved_changes", { count: dirtyCount })}
      </span>
    );
  } else if (isHiddenWhenSaved) {
    return null;
  } else {
    content = (
      <span className="text-muted-foreground inline-flex items-center gap-1.5 text-sm">
        <SuccessMark size="sm" replayKey={justSaved ? landings : undefined} />
        {t(isCompact ? "save_status_saved_short" : "all_changes_saved")}
      </span>
    );
  }

  return <span>{content}</span>;
}
