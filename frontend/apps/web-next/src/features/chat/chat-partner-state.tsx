"use client";

import { Button } from "@astryxdesign/core/Button";
import { CircleAlert } from "lucide-react";
import { useTranslations } from "next-intl";
import { EmptyState } from "@/components/composites/empty-state";
import { LoadingState } from "@/components/composites/loading-state";
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

/** A chat route while its assistant or group chat loads. */
export function ChatPartnerLoading() {
  const t = useTranslations();
  return (
    <div className="mx-auto w-full max-w-[712px] p-6">
      <LoadingState rows={4} label={t("chat_partner_loading")} />
    </div>
  );
}

/**
 * A chat route whose assistant or group chat could not be loaded: what
 * happened and, when it can help, a retry. Without a chat header on the page
 * the shell shows its own top bar, so phones keep the navigation menu.
 */
export function ChatPartnerError({ onRetry }: { onRetry?: () => void }) {
  const t = useTranslations();
  return (
    <div className="mx-auto w-full max-w-[712px] p-6">
      <EmptyState
        icon={<CircleAlert />}
        title={t("chat_partner_load_failed")}
        description={t("chat_partner_load_failed_description")}
        actions={
          onRetry ? (
            <Button label={t("chat_retry")} variant="secondary" onClick={onRetry} />
          ) : undefined
        }
      />
    </div>
  );
}
