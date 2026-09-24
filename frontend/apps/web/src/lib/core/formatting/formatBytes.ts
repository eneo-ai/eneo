import { m } from "$lib/paraglide/messages";
import { intlLocale } from "./dateTime";

const UNITS = [
  () => m.storage_unit_b(),
  () => m.storage_unit_kb(),
  () => m.storage_unit_mb(),
  () => m.storage_unit_gb(),
  () => m.storage_unit_tb()
];

/**
 * A size in bytes as a readable string with base-1024 units, with the number formatted for the
 * UI language ("1.5 MB" / "1,5 MB"). `decimals` is the fixed number of fraction digits.
 */
export function formatBytes(bytes: number, decimals = 0) {
  if (!(bytes > 0)) return `${bytes < 0 ? "-" : "0"} ${m.storage_unit_b()}`;
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), UNITS.length - 1);
  const digits = Math.max(0, decimals);
  const value = new Intl.NumberFormat(intlLocale(), {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  }).format(bytes / 1024 ** exponent);
  return `${value} ${UNITS[exponent]()}`;
}
