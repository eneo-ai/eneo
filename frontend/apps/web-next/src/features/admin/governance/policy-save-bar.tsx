"use client";

import { AlertCircle, CheckCircle2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";

export function PolicySaveBar({
  dirty,
  saveError,
  canSave,
  saving,
  onDiscard,
  onSave
}: {
  dirty: boolean;
  saveError: string | null;
  canSave: boolean;
  saving: boolean;
  onDiscard: () => void;
  onSave: () => void;
}) {
  const t = useTranslations();
  if (!dirty && !saveError) return null;

  return (
    <div
      className="bg-background fixed inset-x-0 bottom-0 z-50 border-t shadow-lg md:left-60"
      role="region"
      aria-label={t("governance_unsaved_changes_aria")}
    >
      <div className="mx-auto flex max-w-[1100px] items-center justify-between gap-4 px-6 py-3">
        <div className="flex items-center gap-2 text-sm">
          {saveError ? (
            <>
              <AlertCircle className="text-destructive size-4 shrink-0" aria-hidden="true" />
              <span className="text-destructive" role="alert">
                {saveError}
              </span>
            </>
          ) : !canSave ? (
            <>
              <AlertCircle className="text-muted-foreground size-4 shrink-0" aria-hidden="true" />
              <span className="text-muted-foreground">{t("governance_fix_validation")}</span>
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
          <Button onClick={onSave} disabled={!canSave || saving} aria-busy={saving}>
            {saving ? t("governance_saving") : t("governance_save_changes")}
          </Button>
        </div>
      </div>
    </div>
  );
}
