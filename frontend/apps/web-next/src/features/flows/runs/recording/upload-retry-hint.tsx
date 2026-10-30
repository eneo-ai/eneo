"use client";

import { useLocale, useTranslations } from "use-intl";

/**
 * When a recorded part whose upload failed goes again by itself: at a time
 * (or as soon as the browser is back online), or no more by itself once its
 * automatic attempts are spent.
 */
export function UploadRetryHint({ nextRetryAt }: { nextRetryAt: number | null | undefined }) {
  const t = useTranslations();
  const locale = useLocale();
  if (nextRetryAt === undefined) return <>{t("flow_transcript_upload_offline_hint")}</>;
  if (nextRetryAt === null) return <>{t("flow_transcript_upload_retry_exhausted")}</>;
  const time = new Intl.DateTimeFormat(locale, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  }).format(nextRetryAt);
  return <>{t("flow_transcript_upload_retry_at", { time })}</>;
}
