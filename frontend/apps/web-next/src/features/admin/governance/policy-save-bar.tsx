"use client";

import { AlertCircle, CheckCircle2 } from "lucide-react";
import { useTranslations } from "use-intl";
import { useRef } from "react";
import { ListError } from "@/components/composites/query-state";
import { Button } from "@/components/ui/button";

/**
 * The governance page's unsaved changes and their Save. Save is never
 * disabled: while a section's problem blocks it, pressing it moves focus to
 * the first such problem (marked data-save-problem), or to this bar's status.
 */
export function PolicySaveBar({
  dirty,
  saveError,
  canSave,
  saving,
  onDiscard,
  onSave
}: {
  dirty: boolean;
  /** The failed save, shown with `ListError`; null when the last save did not fail. */
  saveError: unknown;
  canSave: boolean;
  saving: boolean;
  onDiscard: () => void;
  onSave: () => void;
}) {
  const t = useTranslations();
  const statusRef = useRef<HTMLSpanElement>(null);
  if (!dirty && saveError == null) return null;

  function save() {
    if (saving) return;
    if (!canSave) {
      const problem = document.querySelector<HTMLElement>("[data-save-problem]");
      (problem ?? statusRef.current)?.focus();
      return;
    }
    onSave();
  }

  return (
    <div
      // Sticks to the bottom of the page panel, in the page's own column: it
      // lines up with the content, sits above the home indicator, and the
      // panel scrolls clear of it (a fixed bar was offset for a sidebar that
      // phones and iPads held upright do not have).
      className="bg-background sticky bottom-0 z-10 border-t pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom,0px))] shadow-lg"
      role="region"
      aria-label={t("governance_unsaved_changes_aria")}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 flex-1 items-center gap-2 text-sm">
          {saveError != null ? (
            <ListError error={saveError} title={t("governance_save_error")} compact />
          ) : !canSave ? (
            <>
              <AlertCircle className="text-muted-foreground size-4 shrink-0" aria-hidden="true" />
              <span ref={statusRef} tabIndex={-1} className="text-muted-foreground">
                {t("governance_fix_validation")}
              </span>
            </>
          ) : (
            <>
              <CheckCircle2 className="text-primary size-4 shrink-0" aria-hidden="true" />
              <span className="text-muted-foreground">{t("governance_unsaved_changes")}</span>
            </>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" onClick={onDiscard} disabled={saving}>
            {t("reset")}
          </Button>
          <Button onClick={save} aria-busy={saving}>
            {saving ? t("governance_saving") : t("governance_save_changes")}
          </Button>
        </div>
      </div>
    </div>
  );
}
