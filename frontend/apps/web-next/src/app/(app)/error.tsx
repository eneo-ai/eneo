"use client";

import { Button } from "@astryxdesign/core/Button";
import { useTranslations } from "next-intl";
import { useEffect } from "react";
import { EneoApiError } from "@/lib/api/errors";

/** App-area error boundary: shows the message + trace id (for support) and a retry. */
export default function AppError({
  error,
  reset
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const t = useTranslations();

  useEffect(() => {
    console.error(error);
  }, [error]);

  const traceId = error instanceof EneoApiError ? error.traceId : error.digest;

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8 text-center">
      <h1 className="text-ax-text text-2xl font-semibold">{t("something_went_wrong")}</h1>
      <p className="text-ax-text-secondary max-w-prose text-sm">{t("error_occurred")}</p>
      {traceId && (
        <p className="text-ax-text-secondary font-mono text-xs">
          {t("trace_id")}: {traceId}
        </p>
      )}
      <Button label={t("try_again")} variant="primary" onClick={reset} />
    </div>
  );
}
