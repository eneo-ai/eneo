"use client";

import Link from "@/lib/link";
import { useTranslations } from "use-intl";
import { ListError } from "@/components/composites/query-state";
import { Button } from "@/components/ui/button";

export function ImportPreviewError({
  error,
  message,
  onBack,
  onRetry,
  isRetrying = false,
  settingsHref
}: {
  /** The failed preview request; without one (no connection) only `message` shows. */
  error?: unknown;
  message: string;
  onBack: () => void;
  onRetry?: () => void;
  /** The retry is in flight (the preview query is fetching). */
  isRetrying?: boolean;
  settingsHref?: string | null;
}) {
  const t = useTranslations();
  return (
    <div className="flex flex-col gap-3">
      <ListError error={error} title={message} isRetrying={isRetrying} onRetry={onRetry} />
      <div className="flex flex-wrap gap-2">
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
