"use client";

import { useTranslations } from "use-intl";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { toastApiError } from "@/lib/api/toast";
import { useSetSaveStatus } from "./save-status";

/**
 * Wraps a save operation and drives the page-header status
 * (Saving… / All saved / Couldn't save via SaveStatusProvider). Success is shown
 * by the header alone — no toast, since that would just echo it. Only failures
 * raise a toast, because the header chip is generic and the toast carries the
 * actual error message and trace id.
 *
 * `key` should match the field's section/anchor id so the header error chip can
 * link back to it. The returned runner resolves to the operation's result, or
 * `undefined` if it failed (the error is already surfaced to the user).
 */
export function useAutosave(key: string) {
  const t = useTranslations();
  const setStatus = useSetSaveStatus();
  const state = useRef({ failed: false, pending: 0 });

  // Don't strand a stale status when the field unmounts; a save still in
  // flight keeps reporting until it settles.
  useEffect(() => {
    const current = state.current;
    return () => {
      if (current.pending === 0) setStatus?.(key, null);
    };
  }, [setStatus, key]);

  return useCallback(
    async function run<T>(operation: () => Promise<T>): Promise<T | undefined> {
      state.current.pending += 1;
      setStatus?.(key, "saving");
      try {
        const result = await operation();
        state.current.failed = false;
        return result;
      } catch (error) {
        state.current.failed = true;
        toastApiError(error, t);
        return undefined;
      } finally {
        state.current.pending = Math.max(0, state.current.pending - 1);
        if (state.current.failed) {
          setStatus?.(key, "error");
        } else if (state.current.pending > 0) {
          setStatus?.(key, "saving");
        } else {
          setStatus?.(key, null);
        }
      }
    },
    [setStatus, key, t]
  );
}

/** Report unsaved local draft state to the aggregate save indicator. */
export function useDirtySaveStatus(key: string, dirty: boolean) {
  const setStatus = useSetSaveStatus();
  const dirtyKey = `${key}:dirty`;

  useEffect(() => {
    if (!setStatus) return;
    setStatus(dirtyKey, dirty ? "dirty" : null);
    return () => setStatus(dirtyKey, null);
  }, [dirty, dirtyKey, setStatus]);
}

/**
 * Draft state for a text-like field that autosaves. Holds a local draft seeded
 * from the server value, adopts external server changes only while the user
 * hasn't diverged locally, and on `commit()` saves through {@link useAutosave}
 * when the (optionally normalized) value differs and passes `validate`.
 *
 * The hook owns the whole draft lifecycle: a commit clears the armed debounce,
 * a value already in flight is not sent again (a blur during a slow save would
 * otherwise create a second prompt version), `commit(value)` saves a value the
 * caller has just set before the draft state settles, and a dirty draft is
 * committed when the field unmounts (in-app navigation inside the debounce).
 */
export function useAutosaveField<T, R = unknown>({
  key,
  value: serverValue,
  save,
  equals = Object.is,
  validate,
  normalize,
  onSaved,
  commitDebounceMs,
  commitOnVisibilityChange = false
}: {
  key: string;
  value: T;
  save: (value: T) => Promise<R>;
  /** Compare draft and server values. Defaults to `Object.is`. */
  equals?: (a: T, b: T) => boolean;
  /** Skip the save when the normalized value is invalid. */
  validate?: (value: T) => boolean;
  /** Canonicalize before saving (e.g. trim); the draft adopts the result. */
  normalize?: (value: T) => T;
  /** Runs after a save succeeds, with its result. */
  onSaved?: (result: R) => void;
  /** Commit after the draft has been idle for this many milliseconds. */
  commitDebounceMs?: number;
  /** Commit dirty draft state when the page is hidden. */
  commitOnVisibilityChange?: boolean;
}) {
  const autosave = useAutosave(key);
  const [draft, setDraft] = useState(serverValue);
  const serverRef = useRef(serverValue);
  // The latest value sent and not yet settled: what the server will hold next.
  const inFlight = useRef<{ value: T } | null>(null);
  // The latest value whose save succeeded, until the next server value arrives.
  const landed = useRef<{ value: T } | null>(null);

  useEffect(() => {
    if (equals(serverRef.current, serverValue)) return;
    const previousServer = serverRef.current;
    serverRef.current = serverValue;
    // A server value this hook's own save produced never replaces the draft:
    // the draft is the user's latest choice (it may revert what just landed).
    // Any other value is someone else's change, or the server's canonical form
    // of what this hook saved ("07" comes back as "7"), which a draft the user
    // has not diverged from adopts, also after this hook's own saves failed.
    const mine = landed.current;
    const own = mine !== null && equals(mine.value, serverValue);
    landed.current = null;
    setDraft((current) =>
      !own && (equals(current, previousServer) || (mine !== null && equals(current, mine.value)))
        ? serverValue
        : current
    );
  }, [serverValue, equals]);

  const dirty = !equals(draft, serverValue);
  useDirtySaveStatus(key, dirty);

  // `commit` is stable and reads the latest render, so the debounce timer, the
  // hide handler and the unmount flush never save a stale draft.
  const latest = useRef({
    autosave,
    draft,
    serverValue,
    save,
    equals,
    validate,
    normalize,
    onSaved
  });
  useLayoutEffect(() => {
    latest.current = { autosave, draft, serverValue, save, equals, validate, normalize, onSaved };
  });
  const timer = useRef<number | undefined>(undefined);

  // What the server holds next: the value in flight, else a landed save whose
  // value has not rendered yet, else the rendered server value.
  const serverNext = useCallback(() => {
    const pending = inFlight.current ?? landed.current;
    return pending ? pending.value : latest.current.serverValue;
  }, []);

  // The draft differs from what the server will hold. Measured at the moment
  // of use, so a revert typed while a save is in flight or landing counts.
  const unsent = useCallback(
    () => !latest.current.equals(latest.current.draft, serverNext()),
    [serverNext]
  );

  const commit = useCallback(
    async (override?: T) => {
      window.clearTimeout(timer.current);
      const { autosave, draft, save, equals, validate, normalize, onSaved } = latest.current;
      const value = override === undefined ? draft : override;
      const next = normalize ? normalize(value) : value;
      if (normalize && !equals(next, value)) setDraft(next);
      // Compare with what the server will hold: a value already in flight is not
      // sent again, and returning to the old value during a save is sent.
      if (equals(next, serverNext())) return;
      if (validate && !validate(next)) return;
      const flight = { value: next };
      inFlight.current = flight;
      await autosave(async () => {
        const result = await save(next);
        landed.current = flight;
        onSaved?.(result);
        return result;
      });
      if (inFlight.current === flight) inFlight.current = null;
    },
    [serverNext]
  );

  const reset = useCallback(() => setDraft(serverValue), [serverValue]);

  // Re-armed by edits only: a settling save (even a failed one) does not
  // start another, so an outage is not retried in a loop.
  useEffect(() => {
    if (!commitDebounceMs) return;
    const id = window.setTimeout(() => {
      if (unsent()) void commit();
    }, commitDebounceMs);
    timer.current = id;
    return () => window.clearTimeout(id);
  }, [commit, commitDebounceMs, draft, unsent]);

  useEffect(() => {
    if (!commitOnVisibilityChange) return;
    const handler = () => {
      if (document.visibilityState === "hidden" && unsent()) void commit();
    };
    document.addEventListener("visibilitychange", handler);
    return () => document.removeEventListener("visibilitychange", handler);
  }, [commit, commitOnVisibilityChange, unsent]);

  // Flush unsaved intent only (fire-and-forget; the save still reports through
  // the page's save status): an untouched field is never written on unmount.
  useEffect(
    () => () => {
      if (unsent()) void commit();
    },
    [commit, unsent]
  );

  return { value: draft, setValue: setDraft, dirty, commit, reset };
}
