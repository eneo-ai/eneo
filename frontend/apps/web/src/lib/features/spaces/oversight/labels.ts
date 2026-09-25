import { intlLocale } from "$lib/core/formatting/dateTime";
import { findHostingLabel } from "$lib/features/ai-models/hosting/hostingOptions";
import { m } from "$lib/paraglide/messages";

/** "GPT-5 · EU", the model's name and where it is hosted when known. */
export function modelLabel(model: { name: string; hosting?: string | null }): string {
  const hosting = model.hosting
    ? findHostingLabel(model.hosting) || model.hosting.toUpperCase()
    : "";
  return hosting ? `${model.name} · ${hosting}` : model.name;
}

/**
 * "1 000 dagar" / "1 dag" for a retention in days. Without a value of its
 * own the setting is inherited, and `inherited` says from where.
 */
export function retentionLabel(days: number | null | undefined, inherited: string): string {
  if (days == null) return inherited;
  return days === 1
    ? m.admin_spaces_retention_days_one()
    : m.admin_spaces_retention_days({ days: new Intl.NumberFormat(intlLocale()).format(days) });
}
