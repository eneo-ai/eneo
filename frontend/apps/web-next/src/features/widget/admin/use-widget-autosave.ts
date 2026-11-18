"use client";

import { useTranslations } from "use-intl";
import { useEffect, useState, useSyncExternalStore } from "react";
import { useSetSaveStatus } from "@/components/composites/save-status";
import type { Schema } from "@/lib/api/models";
import { WidgetAutosave, type AutosaveSnapshot } from "./autosave";
import { toastWidgetError, widgetFieldErrors } from "./errors";
import { widgetApi } from "./queries";
import { useAutosaveNavigationGuard } from "./use-autosave-navigation-guard";

type Widget = Schema<"WidgetPublic">;

/** The header's save chip: the page's autosave reported like any other field's. */
const SAVE_STATUS_KEY = "widget-editor";

/** What the hook needs of a store; the generic class itself varies in its update type. */
type AutosaveStore = {
  subscribe: (listener: () => void) => () => void;
  getSnapshot: () => AutosaveSnapshot<unknown>;
  unsaved: boolean;
  stranded: boolean;
  flush: () => Promise<void>;
  dispose: () => void;
};

/**
 * One autosave store, kept for the component's lifetime. Its state is read
 * through React's external-store hook, so every edit, save and refusal
 * re-renders what shows them; the header's aggregate save status follows
 * it under `statusKey`, which also guards reload and tab close while
 * something is unsaved (SaveStatusProvider), and in-app navigation waits for
 * the queued edits (useAutosaveNavigationGuard). Whatever is still pending
 * gets one last attempt when the component unmounts.
 */
export function useAutosave<Store extends AutosaveStore>(
  create: () => Store,
  statusKey: string
): { autosave: Store; state: ReturnType<Store["getSnapshot"]> } {
  const [autosave] = useState(create);
  const state = useSyncExternalStore(
    autosave.subscribe,
    autosave.getSnapshot,
    autosave.getSnapshot
  ) as AutosaveSnapshot<unknown>;

  const setStatus = useSetSaveStatus();
  useEffect(() => {
    if (!setStatus) return;
    const status =
      state.status === "saving"
        ? "saving"
        : state.status === "error" || state.status === "conflict" || state.status === "refused"
          ? "error"
          : state.unsaved
            ? "dirty"
            : null;
    setStatus(statusKey, status);
  }, [setStatus, statusKey, state.status, state.unsaved]);

  useAutosaveNavigationGuard(autosave);

  useEffect(() => {
    return () => {
      setStatus?.(statusKey, null);
      void autosave.flush().finally(() => autosave.dispose());
    };
  }, [autosave, setStatus, statusKey]);

  return { autosave, state: state as ReturnType<Store["getSnapshot"]> };
}

/**
 * The autosave of the widget being edited (the widget page). Every saved
 * widget is reported to `onSaved` as the save completes, also after the
 * editor has unmounted: the page's list must follow a save that finishes
 * after a confirmed navigation, or reopening within its stale time would
 * rebuild the editor from the old revision.
 */
export function useWidgetAutosave(
  widget: Widget,
  onSaved?: (widget: Widget) => void
): {
  autosave: WidgetAutosave;
  state: AutosaveSnapshot<Widget>;
} {
  const t = useTranslations();
  return useAutosave(
    () =>
      new WidgetAutosave(
        widget,
        async (update) => {
          try {
            const saved = await widgetApi.update(widget.id, update);
            onSaved?.(saved);
            return saved;
          } catch (error) {
            toastWidgetError(error, t);
            throw error;
          }
        },
        { fieldErrors: (error) => widgetFieldErrors(error, t) }
      ),
    SAVE_STATUS_KEY
  );
}
