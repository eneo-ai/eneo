"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState, useSyncExternalStore } from "react";
import { useSetSaveStatus } from "@/components/composites/save-status";
import type { Schema } from "@/lib/api/models";
import { WidgetAutosave, type AutosaveSnapshot } from "./autosave";
import { toastWidgetError, widgetFieldErrors } from "./errors";
import { widgetApi } from "./queries";

type Widget = Schema<"WidgetPublic">;

/** The header's save chip: the page's autosave reported like any other field's. */
const SAVE_STATUS_KEY = "widget-editor";

/**
 * One autosave for the widget being edited, kept for the editor's lifetime.
 * Its state is read through React's external-store hook, so every edit,
 * save and refusal re-renders what shows them; the header's aggregate save
 * status follows it, which also guards reload and tab close while something
 * is unsaved (SaveStatusProvider).
 */
export function useWidgetAutosave(widget: Widget): {
  autosave: WidgetAutosave;
  state: AutosaveSnapshot<Widget>;
} {
  const t = useTranslations();
  const [autosave] = useState(
    () =>
      new WidgetAutosave(
        widget,
        async (update) => {
          try {
            return await widgetApi.update(widget.id, update);
          } catch (error) {
            toastWidgetError(error, t);
            throw error;
          }
        },
        { fieldErrors: (error) => widgetFieldErrors(error, t) }
      )
  );
  const state = useSyncExternalStore(
    autosave.subscribe,
    autosave.getSnapshot,
    autosave.getSnapshot
  );

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
    setStatus(SAVE_STATUS_KEY, status);
  }, [setStatus, state.status, state.unsaved]);

  useEffect(() => {
    return () => {
      setStatus?.(SAVE_STATUS_KEY, null);
      // Whatever is still pending gets one last attempt on the way out.
      void autosave.flush().finally(() => autosave.dispose());
    };
  }, [autosave, setStatus]);

  return { autosave, state };
}
