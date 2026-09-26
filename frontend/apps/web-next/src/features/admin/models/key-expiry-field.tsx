"use client";

import { DateInput, type DateInputProps } from "@astryxdesign/core/DateInput";
import { useTranslations } from "next-intl";
import { KEY_EXPIRY_WARNING_DAYS } from "./key-expiry";

type IsoDate = NonNullable<DateInputProps["value"]>;

function isIsoDate(value: string | null): value is IsoDate {
  return value !== null && /^\d{4}-\d{2}-\d{2}$/.test(value);
}

/**
 * The optional date a provider's API key expires, as YYYY-MM-DD or null.
 *
 * `nativePicker="never"`: the browser-picker surface probes the engine with an
 * injected <style>, which the production CSP blocks (AGENTS.md → CSP); Astryx's
 * own calendar and touch picker inject nothing.
 */
export function KeyExpiryField({
  value,
  onChange
}: {
  value: string | null;
  onChange: (value: string | null) => void;
}) {
  const t = useTranslations();
  return (
    <DateInput
      label={t("provider_status_key_expiry_label")}
      description={t("provider_status_key_expiry_description", {
        days: KEY_EXPIRY_WARNING_DAYS
      })}
      isOptional
      hasClear
      nativePicker="never"
      weekStartsOn="mon"
      value={isIsoDate(value) ? value : undefined}
      onChange={(next) => onChange(next ?? null)}
    />
  );
}
