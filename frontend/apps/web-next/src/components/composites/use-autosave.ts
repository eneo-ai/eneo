"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";
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

  // Don't strand a stale status if the field unmounts mid-save.
  useEffect(() => () => setStatus?.(key, null), [setStatus, key]);

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
 * Draft state for a text-like field that autosaves on blur. Holds a local draft
 * seeded from the server value, adopts external server changes only while the
 * user hasn't diverged locally, and on `commit()` saves through {@link useAutosave}
 * when the (optionally normalized) value differs and passes `validate`.
 */
export function useAutosaveField<T>({
  key,
  value: serverValue,
  save,
  equals = Object.is,
  validate,
  normalize,
  commitDebounceMs,
  commitOnVisibilityChange = false
}: {
  key: string;
  value: T;
  save: (value: T) => Promise<unknown>;
  /** Compare draft and server values. Defaults to `Object.is`. */
  equals?: (a: T, b: T) => boolean;
  /** Skip the save when the normalized value is invalid. */
  validate?: (value: T) => boolean;
  /** Canonicalize before saving (e.g. trim); the draft adopts the result. */
  normalize?: (value: T) => T;
  /** Commit after the draft has been idle for this many milliseconds. */
  commitDebounceMs?: number;
  /** Commit dirty draft state when the page is hidden. */
  commitOnVisibilityChange?: boolean;
}) {
  const autosave = useAutosave(key);
  const [draft, setDraft] = useState(serverValue);
  const serverRef = useRef(serverValue);

  useEffect(() => {
    if (equals(serverRef.current, serverValue)) return;
    const previousServer = serverRef.current;
    serverRef.current = serverValue;
    setDraft((current) => (equals(current, previousServer) ? serverValue : current));
  }, [serverValue, equals]);

  const dirty = !equals(draft, serverValue);
  useDirtySaveStatus(key, dirty);

  const commit = useCallback(async () => {
    const next = normalize ? normalize(draft) : draft;
    if (normalize && !equals(next, draft)) setDraft(next);
    if (equals(next, serverValue)) return;
    if (validate && !validate(next)) return;
    await autosave(() => save(next));
  }, [autosave, draft, equals, normalize, save, serverValue, validate]);

  const reset = useCallback(() => setDraft(serverValue), [serverValue]);

  useEffect(() => {
    if (!commitDebounceMs || !dirty) return;
    const timer = window.setTimeout(() => void commit(), commitDebounceMs);
    return () => window.clearTimeout(timer);
  }, [commit, commitDebounceMs, dirty]);

  useEffect(() => {
    if (!commitOnVisibilityChange || !dirty) return;
    const handler = () => {
      if (document.visibilityState === "hidden") void commit();
    };
    document.addEventListener("visibilitychange", handler);
    return () => document.removeEventListener("visibilitychange", handler);
  }, [commit, commitOnVisibilityChange, dirty]);

  return { value: draft, setValue: setDraft, dirty, commit, reset };
}
