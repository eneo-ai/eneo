"use client";

import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Text } from "@astryxdesign/core/Text";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import { ClientTime } from "@/components/composites/client-time";
import { StatusLabel, type StatusTone } from "@/components/composites/status-label";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import { useHydrated } from "@/lib/hooks/use-hydrated";
import { toast } from "@/lib/toast";
import { keyExpiry, localIsoDate } from "./key-expiry";
import {
  checkProviderConnection,
  type ConnectionCheckError,
  type ModelProvider,
  PROVIDERS_KEY
} from "./model-providers";

type Translate = ReturnType<typeof useTranslations>;

/** The short reason that follows "Anslutningen misslyckades:". */
function failureReason(t: Translate, error: ConnectionCheckError | null | undefined): string {
  switch (error) {
    case "authentication_failed":
      return t("provider_status_reason_authentication_failed");
    case "missing_credentials":
      return t("provider_status_reason_missing_credentials");
    case "not_found":
      return t("provider_status_reason_not_found");
    case "rate_limited":
      return t("provider_status_reason_rate_limited");
    case "rejected":
      return t("provider_status_reason_rejected");
    case "provider_error":
      return t("provider_status_reason_provider_error");
    case "timeout":
      return t("provider_status_reason_timeout");
    case "unreachable":
      return t("provider_status_reason_unreachable");
    default:
      return t("provider_status_reason_unknown");
  }
}

function connectionStatus(t: Translate, provider: ModelProvider): [StatusTone, string] {
  const check = provider.connection_check;
  if (check?.status === "ok") return ["success", t("provider_status_ok")];
  if (check?.status === "failed") {
    return ["error", t("provider_status_failed", { reason: failureReason(t, check.error) })];
  }
  return provider.connection_check_supported
    ? ["neutral", t("provider_status_not_tested")]
    : ["neutral", t("provider_status_unsupported")];
}

/**
 * A provider's connection line: the latest check ("Anslutningen fungerar",
 * "Anslutningen misslyckades: <orsak>" or "Inte testad") and when it ran, the
 * key-expiry notice, and "Testa anslutning". The expiry and the check time
 * depend on the viewer's clock, so they appear after hydration.
 */
export function ProviderConnectionStatus({ provider }: { provider: ModelProvider }) {
  const t = useTranslations();
  const format = useFormatter();
  const announce = useAnnounce();
  const queryClient = useQueryClient();
  const hydrated = useHydrated();

  const check = useMutation({
    mutationFn: () => checkProviderConnection(browserApi, provider.id),
    onSuccess: (updated) => {
      queryClient.setQueryData<ModelProvider[]>(PROVIDERS_KEY, (current) =>
        current?.map((item) => (item.id === updated.id ? updated : item))
      );
      const result = updated.connection_check;
      // No result: the key or endpoint changed during the check.
      if (!result) return;
      // Announced once: a failure through its toast (which stays until
      // closed), a success through the live region.
      if (result.status === "ok") {
        announce(t("provider_status_announce_ok", { name: provider.name }));
      } else {
        toast.error(
          t("provider_status_announce_failed", {
            name: provider.name,
            reason: failureReason(t, result.error)
          })
        );
      }
    },
    onError: (error) => toastApiError(error, t)
  });

  const [tone, label] = connectionStatus(t, provider);
  const checkedAt = provider.connection_check?.checked_at;
  const today = hydrated ? localIsoDate(new Date()) : null;
  const expiry = today ? keyExpiry(provider.key_expires_on, today) : null;
  const expiryDate = expiry
    ? format.dateTime(new Date(`${expiry.date}T00:00:00Z`), {
        day: "numeric",
        month: "short",
        // The year only when it isn't this one: "12 okt." but "12 jan. 2027".
        year: expiry.date.slice(0, 4) === today?.slice(0, 4) ? undefined : "numeric",
        timeZone: "UTC"
      })
    : null;

  return (
    <div className="border-ax-border flex flex-wrap items-center gap-x-4 gap-y-2 border-b py-2 ps-4 pe-2.5">
      <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1">
        <StatusLabel status={tone} label={label} />
        {hydrated && checkedAt ? (
          <Text type="supporting">
            {t.rich("provider_status_checked_at", {
              time: () => <ClientTime value={checkedAt} format="relative" />
            })}
          </Text>
        ) : null}
        {expiry && expiryDate ? (
          <StatusLabel
            status={expiry.state === "expired" ? "error" : "warning"}
            label={
              expiry.state === "expired"
                ? t("provider_status_key_expired", { date: expiryDate })
                : t("provider_status_key_expiring", { date: expiryDate })
            }
          />
        ) : null}
      </div>
      {provider.connection_check_supported ? (
        <Button
          size="sm"
          className="ms-auto"
          // The name says which provider (one button per card) and stays so
          // while busy; the visible text starts it (WCAG 2.5.3).
          label={t("provider_status_test_named", { name: provider.name })}
          // Stays focusable while the check runs; a second press is ignored.
          isLoading={check.isPending}
          isInterruptible
          onClick={() => {
            if (!check.isPending) check.mutate();
          }}
        >
          {t("test_connection")}
        </Button>
      ) : null}
    </div>
  );
}
