/*
 * Copyright (c) 2026 Sundsvalls Kommun
 *
 * Request vocabulary of image generation models. Mirrors IMAGE_SIZES /
 * IMAGE_QUALITIES in the backend image model domain; "auto" sends nothing
 * so the model decides.
 */
import { m } from "$lib/paraglide/messages";

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

export function imageSizeLabel(size: string | null | undefined): string {
  if (!size || size === "auto") return m.image_option_auto();
  return size;
}

export function imageQualityLabel(quality: string | null | undefined): string {
  switch (quality) {
    case "low":
      return m.image_quality_low();
    case "medium":
      return m.image_quality_medium();
    case "high":
      return m.image_quality_high();
    default:
      return m.image_option_auto();
  }
}
