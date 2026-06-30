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

  // Don't strand a stale status if the field unmounts mid-save.
  useEffect(() => () => setStatus?.(key, null), [setStatus, key]);

  return useCallback(
    async function run<T>(operation: () => Promise<T>): Promise<T | undefined> {
      setStatus?.(key, "saving");
      try {
        const result = await operation();
        setStatus?.(key, null);
        return result;
      } catch (error) {
        setStatus?.(key, "error");
        toastApiError(error, t);
        return undefined;
      }
    },
    [setStatus, key, t]
  );
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
  normalize
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

  const commit = useCallback(async () => {
    const next = normalize ? normalize(draft) : draft;
    if (normalize && !equals(next, draft)) setDraft(next);
    if (equals(next, serverValue)) return;
    if (validate && !validate(next)) return;
    await autosave(() => save(next));
  }, [autosave, draft, equals, normalize, save, serverValue, validate]);

  const reset = useCallback(() => setDraft(serverValue), [serverValue]);

  return { value: draft, setValue: setDraft, dirty, commit, reset };
}
