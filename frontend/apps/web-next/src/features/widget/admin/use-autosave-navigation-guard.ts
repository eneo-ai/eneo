import { useLeaveConfirmation } from "@/lib/navigation";
import { useTranslations } from "use-intl";
import { useEffect, useEffectEvent } from "react";

/** What the navigation guard needs of the canonical autosave store. */
export type GuardedAutosave = {
  unsaved: boolean;
  stranded: boolean;
  flush: () => Promise<void>;
};

/** Hold links and browser history transitions while the queued edits are saved. */
export function useAutosaveNavigationGuard(autosave: GuardedAutosave): void {
  const confirmation = useLeaveConfirmation(autosave.unsaved);
  const t = useTranslations();
  const leave = useEffectEvent(() => confirmation.leave());
  const stay = useEffectEvent(() => confirmation.stay());
  useEffect(() => {
    if (!confirmation.blocked) return;
    if (autosave.stranded) {
      if (window.confirm(t("widget_admin_unsaved_leave_confirm"))) leave();
      else stay();
      return;
    }
    let cancelled = false;
    void autosave
      .flush()
      .then(() => {
        if (cancelled) return;
        if (autosave.unsaved) stay();
        else leave();
      })
      .catch(() => {
        if (!cancelled) stay();
      });
    return () => {
      cancelled = true;
    };
    // A blocker preserves the native destination and history action. Its methods
    // can change each render; one flush belongs to each blocked transition.
  }, [autosave, confirmation.blocked, t]);
}
