"use client";

import { Button } from "@astryxdesign/core/Button";
import { useQueryErrorResetBoundary } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { useEffect } from "react";
import { errorReferenceLines } from "@/lib/api/errors";
import { useCopy } from "@/lib/hooks/use-copy";

/**
 * A page that failed to load or render: what happened, the references
 * support asks for (error id and trace id) and a retry. The retry also lets
 * the page's failed suspense queries load again instead of rethrowing their
 * error.
 */
export function RouteError({ error, reset }: { error: unknown; reset: () => void }) {
  const t = useTranslations();
  const queryErrors = useQueryErrorResetBoundary();
  const references = errorReferenceLines(error, t);
  const { copy, isCopied } = useCopy();

  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8 text-center">
      <h1 className="text-ax-text text-2xl font-semibold">{t("something_went_wrong")}</h1>
      <p className="text-ax-text-secondary max-w-prose text-sm">{t("error_occurred")}</p>
      {references.map((line) => (
        <p key={line} className="text-ax-text-secondary max-w-full font-mono text-xs break-all">
          {line}
        </p>
      ))}
      {references.length > 0 && (
        <Button
          type="button"
          label={t(isCopied ? "copied" : "copy")}
          onClick={() => {
            void copy(references.join("\n"));
          }}
        />
      )}
      <Button
        label={t("try_again")}
        variant="primary"
        onClick={() => {
          queryErrors.reset();
          reset();
        }}
      />
      <p className="text-ax-text-secondary text-sm">
        {t("error_persists")}{" "}
        <a
          href="/logout"
          className="text-ax-text-accent inline-flex min-h-11 items-center underline underline-offset-4"
        >
          {t("delete_cookies")}
        </a>
      </p>
    </div>
  );
}
