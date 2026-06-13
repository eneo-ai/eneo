"use client";

import { useTranslations } from "next-intl";
import { useEffect } from "react";
import { Button } from "@/components/ui/button";
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
      <h1 className="text-2xl font-semibold">{t("something_went_wrong")}</h1>
      <p className="text-muted-foreground max-w-prose text-sm">{error.message}</p>
      {traceId && (
        <p className="text-muted-foreground font-mono text-xs">
          {t("trace_id")}: {traceId}
        </p>
      )}
      <Button onClick={reset}>{t("try_again")}</Button>
    </div>
  );
}
