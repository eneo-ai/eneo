import { useFormatter, useTranslations } from "next-intl";
import type { StatusTone } from "@/components/composites/status-label";
import { useHydrated } from "@/lib/hooks/use-hydrated";
import { type KeyExpiry, keyExpiry, localIsoDate } from "./key-expiry";
import type { ConnectionCheckError, ModelProvider } from "./model-providers";
import type { ProviderStatus } from "./provider-sections";

/** A provider state as a StatusLabel shows it: colour plus the words. */
export type ProviderNotice = { tone: StatusTone; label: string };

/**
 * The words and tones for a provider's state, shared by its card and the
 * models page banner so both say the same thing. Key expiry depends on the
 * viewer's date, so `today` is null (and there is no expiry notice) until
 * hydration.
 */
export function useProviderNotices() {
  const t = useTranslations();
  const format = useFormatter();
  const hydrated = useHydrated();
  const today = hydrated ? localIsoDate(new Date()) : null;

  /** The short reason that follows "Anslutningen misslyckades:". */
  function failureReason(error: ConnectionCheckError | null | undefined): string {
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

  /** A setup problem shown by the provider's name; none when it is configured. */
  function setup(status: ProviderStatus): ProviderNotice | null {
    if (status === "missing_key") return { tone: "warning", label: t("key_missing") };
    if (status === "inactive") return { tone: "neutral", label: t("inactive") };
    return null;
  }

  /** The latest connection check, or why there is none. */
  function connection(provider: ModelProvider): ProviderNotice {
    const check = provider.connection_check;
    if (check?.status === "ok") return { tone: "success", label: t("provider_status_ok") };
    if (check?.status === "failed") {
      return {
        tone: "error",
        label: t("provider_status_failed", { reason: failureReason(check.error) })
      };
    }
    return {
      tone: "neutral",
      label: provider.connection_check_supported
        ? t("provider_status_not_tested")
        : t("provider_status_unsupported")
    };
  }

  /** Where the provider's key stands against the viewer's date. */
  function expiryOf(provider: ModelProvider): KeyExpiry | null {
    return today ? keyExpiry(provider.key_expires_on, today) : null;
  }

  /** "Nyckeln går ut 12 okt." or "Nyckeln har gått ut 3 okt.". */
  function expiryNotice(expiry: KeyExpiry): ProviderNotice {
    const date = format.dateTime(new Date(`${expiry.date}T00:00:00Z`), {
      day: "numeric",
      month: "short",
      // The year only when it isn't this one: "12 okt." but "12 jan. 2027".
      year: expiry.date.slice(0, 4) === today?.slice(0, 4) ? undefined : "numeric",
      timeZone: "UTC"
    });
    return expiry.state === "expired"
      ? { tone: "error", label: t("provider_status_key_expired", { date }) }
      : { tone: "warning", label: t("provider_status_key_expiring", { date }) };
  }

  return { today, failureReason, setup, connection, expiryOf, expiryNotice };
}
