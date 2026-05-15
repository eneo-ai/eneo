import { getLocale } from "$lib/paraglide/runtime";

export function formatCrawlerCount(count: number): string {
  return new Intl.NumberFormat(getLocale(), {
    maximumFractionDigits: 0
  }).format(Math.max(Math.trunc(count), 0));
}

export function formatCrawlerDecimal(value: number): string {
  return new Intl.NumberFormat(getLocale(), {
    maximumFractionDigits: 1
  }).format(Math.max(value, 0));
}

export function formatCrawlerPercent(value: number): string {
  return new Intl.NumberFormat(getLocale(), {
    maximumFractionDigits: 0,
    style: "percent"
  }).format(Math.min(Math.max(value, 0), 1));
}
