import { getLocale } from "$lib/paraglide/runtime";

export function formatNumber(
  num: number,
  options: "compact" | "full" = "full",
  decimals = 0
): string {
  if (isNaN(num)) return "0";

  if (num === 0) return "0";

  if (num < 0) return "-" + formatNumber(-num, options, decimals);

  if (options === "full") {
    return new Intl.NumberFormat(getLocale(), {
      maximumFractionDigits: 0
    }).format(num);
  } else {
    const k = 1000;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ["", "K", "M", "B", "T"];

    const i = Math.floor(Math.log(num) / Math.log(k));

    if (i === 0) return num.toString();

    return `${(num / Math.pow(k, i)).toFixed(dm)}${sizes[i]}`;
  }
}
