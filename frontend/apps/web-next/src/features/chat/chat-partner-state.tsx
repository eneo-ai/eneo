"use client";

import { useTranslations } from "use-intl";
import { LoadingState } from "@/components/composites/loading-state";
import { ListError } from "@/components/composites/query-state";
import { EneoApiError } from "@/lib/api/errors";

/**
 * Retry policy for a chat route's partner (assistant or group chat) query:
 * a missing or forbidden partner won't appear on retry, so fail at once and
 * show the error; server and network failures get the usual three retries.
 */
export function retryPartnerQuery(failureCount: number, error: unknown): boolean {
  if (error instanceof EneoApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < 3;
}

/** A chat route while its assistant or group chat loads; the page's h1 says so. */
export function ChatPartnerLoading() {
  const t = useTranslations();
  return (
    <div className="mx-auto w-full max-w-[712px] p-6">
      <h1 className="sr-only">{t("chat_partner_loading")}</h1>
      <LoadingState rows={4} label={t("chat_partner_loading")} />
    </div>
  );
}

/**
 * A chat route whose assistant or group chat could not be loaded: what
 * happened (the page's h1), why it may have happened and the failure itself
 * (`ListError`: message, support references and, when it can help, a retry).
 * Without a chat header on the page the shell shows its own top bar, so
 * phones keep the navigation menu.
 */
export function ChatPartnerError({ error, onRetry }: { error?: unknown; onRetry?: () => void }) {
  const t = useTranslations();
  return (
    <div className="mx-auto flex w-full max-w-[712px] flex-col gap-3 p-6">
      <h1 className="text-lg font-semibold">{t("chat_partner_load_failed")}</h1>
      <p className="text-ax-text-secondary text-sm">{t("chat_partner_load_failed_description")}</p>
      <ListError error={error} onRetry={onRetry} compact />
    </div>
  );
}
