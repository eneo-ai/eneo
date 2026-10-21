"use client";

import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Text } from "@astryxdesign/core/Text";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { ClientTime } from "@/components/composites/client-time";
import { StatusLabel } from "@/components/composites/status-label";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import { useHydrated } from "@/lib/hooks/use-hydrated";
import { toast } from "@/lib/toast";
import { checkProviderConnection, type ModelProvider, PROVIDERS_KEY } from "./model-providers";
import { useProviderNotices } from "./provider-notices";

/**
 * A provider's connection line: the latest check ("Anslutningen fungerar",
 * "Anslutningen misslyckades: <orsak>" or "Inte testad") and when it ran, the
 * key-expiry notice, and "Testa anslutning". The expiry and the check time
 * depend on the viewer's clock, so they appear after hydration.
 */
export function ProviderConnectionStatus({ provider }: { provider: ModelProvider }) {
  const t = useTranslations();
  const announce = useAnnounce();
  const queryClient = useQueryClient();
  const notices = useProviderNotices();
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
            reason: notices.failureReason(result.error)
          })
        );
      }
    },
    onError: (error) => toastApiError(error, t)
  });

  const connection = notices.connection(provider);
  const checkedAt = provider.connection_check?.checked_at;
  const expiry = notices.expiryOf(provider);
  const expiryNotice = expiry ? notices.expiryNotice(expiry) : null;

  return (
    <div className="border-ax-border flex flex-wrap items-center gap-x-4 gap-y-2 border-b py-2 ps-4 pe-2.5">
      <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1">
        <StatusLabel status={connection.tone} label={connection.label} />
        {hydrated && checkedAt ? (
          <Text type="supporting">
            {t.rich("provider_status_checked_at", {
              time: () => <ClientTime value={checkedAt} format="relative" />
            })}
          </Text>
        ) : null}
        {expiryNotice ? (
          <StatusLabel status={expiryNotice.tone} label={expiryNotice.label} />
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
