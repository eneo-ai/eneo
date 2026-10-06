"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";

export function ImportPreviewError({
  message,
  onBack,
  onRetry,
  settingsHref
}: {
  message: string;
  onBack: () => void;
  onRetry?: () => void;
  settingsHref?: string | null;
}) {
  const t = useTranslations();
  return (
    <div className="border-destructive/30 bg-destructive/10 text-destructive flex flex-col gap-3 rounded-md border px-3 py-3 text-sm">
      <p>{message}</p>
      <div className="flex flex-wrap gap-2">
        {onRetry ? (
          <Button type="button" size="sm" variant="outline" onClick={onRetry}>
            {t("retry")}
          </Button>
        ) : null}
        {settingsHref ? (
          <Button type="button" size="sm" variant="outline" asChild>
            <Link href={settingsHref}>{t("account_settings")}</Link>
          </Button>
        ) : null}
        <Button type="button" size="sm" variant="outline" onClick={onBack}>
          {t("back")}
        </Button>
      </div>
    </div>
  );
}
