import { useTranslations } from "next-intl";

/**
 * Request vocabulary of image generation models. Mirrors IMAGE_SIZES /
 * IMAGE_QUALITIES in the backend image model domain (and the tenant image
 * model schemas); "auto" sends nothing so the model decides.
 */
export const IMAGE_SIZES = ["auto", "1024x1024", "1536x1024", "1024x1536"] as const;
export type ImageSize = (typeof IMAGE_SIZES)[number];

export const IMAGE_QUALITIES = ["auto", "low", "medium", "high"] as const;
export type ImageQuality = (typeof IMAGE_QUALITIES)[number];

export function isImageSize(value: unknown): value is ImageSize {
  return typeof value === "string" && (IMAGE_SIZES as readonly string[]).includes(value);
}

export function isImageQuality(value: unknown): value is ImageQuality {
  return typeof value === "string" && (IMAGE_QUALITIES as readonly string[]).includes(value);
}

/** Translated labels for an image model's default size and quality. */
export function useImageOptionLabels() {
  const t = useTranslations();
  return {
    size: (size: string | null | undefined): string =>
      !size || size === "auto" ? t("image_option_auto") : size,
    quality: (quality: string | null | undefined): string => {
      switch (quality) {
        case "low":
          return t("image_quality_low");
        case "medium":
          return t("image_quality_medium");
        case "high":
          return t("image_quality_high");
        default:
          return t("image_option_auto");
      }
    }
  };
}
