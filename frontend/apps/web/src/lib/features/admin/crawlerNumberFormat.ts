import { getLocale } from "$lib/paraglide/runtime";

export function formatCrawlerCount(count: number): string {
  return new Intl.NumberFormat(getLocale(), {
    maximumFractionDigits: 0
  }).format(Math.max(Math.trunc(count), 0));
}
