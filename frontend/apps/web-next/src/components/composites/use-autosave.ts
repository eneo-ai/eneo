"use client";

import { useTranslations } from "next-intl";
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

  useEffect(() => {
    if (equals(serverRef.current, serverValue)) return;
    const previousServer = serverRef.current;
    serverRef.current = serverValue;
    // A draft the user has not diverged from adopts the new value, unless it is
    // the newer value still on its way (a choice reverted during a slow save).
    const pending = inFlight.current;
    setDraft((current) =>
      equals(current, previousServer) && !(pending && equals(current, pending.value))
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

  const commit = useCallback(async (override?: T) => {
    window.clearTimeout(timer.current);
    const { autosave, draft, serverValue, save, equals, validate, normalize, onSaved } =
      latest.current;
    const value = override === undefined ? draft : override;
    const next = normalize ? normalize(value) : value;
    if (normalize && !equals(next, value)) setDraft(next);
    // Compare with what the server will hold: a value already in flight is not
    // sent again, and returning to the old value during a save is sent.
    if (equals(next, inFlight.current ? inFlight.current.value : serverValue)) return;
    if (validate && !validate(next)) return;
    const flight = { value: next };
    inFlight.current = flight;
    await autosave(async () => {
      const result = await save(next);
      onSaved?.(result);
      return result;
    });
    if (inFlight.current === flight) inFlight.current = null;
  }, []);

  const reset = useCallback(() => setDraft(serverValue), [serverValue]);

  useEffect(() => {
    if (!commitDebounceMs || !dirty) return;
    const id = window.setTimeout(() => void commit(), commitDebounceMs);
    timer.current = id;
    return () => window.clearTimeout(id);
  }, [commit, commitDebounceMs, dirty, draft]);

  useEffect(() => {
    if (!commitOnVisibilityChange || !dirty) return;
    const handler = () => {
      if (document.visibilityState === "hidden") void commit();
    };
    document.addEventListener("visibilitychange", handler);
    return () => document.removeEventListener("visibilitychange", handler);
  }, [commit, commitOnVisibilityChange, dirty]);

  // Flush unsaved intent only (fire-and-forget; the save still reports through
  // the page's save status): an untouched field is never written on unmount.
  useEffect(
    () => () => {
      const { draft, serverValue, equals } = latest.current;
      if (inFlight.current || !equals(draft, serverValue)) void commit();
    },
    [commit]
  );

  return { value: draft, setValue: setDraft, dirty, commit, reset };
}
