import type { FlowRunDebugRagReference } from "@intric/intric-js";

export type KnowledgeRelevanceLevel = "high" | "moderate" | "low";

export function getKnowledgeRelevanceLevel(score: number): KnowledgeRelevanceLevel {
  if (score >= 0.5) return "high";
  if (score >= 0.3) return "moderate";
  return "low";
}

export function getKnowledgeRelevanceBadgeClass(score: number): string {
  switch (getKnowledgeRelevanceLevel(score)) {
    case "high":
      return "bg-positive-dimmer text-positive-stronger";
    case "moderate":
      return "bg-warning-dimmer text-warning-stronger";
    case "low":
      return "bg-negative-dimmer text-negative-stronger";
  }
}

export function formatKnowledgeSourceLabel(
  title: string | null | undefined,
  sourceUrl: string | null | undefined = null,
  {
    maxPathLength = 40,
    maxFallbackLength = 60
  }: {
    maxPathLength?: number;
    maxFallbackLength?: number;
  } = {}
): string {
  const trimmedTitle = title?.trim();
  if (trimmedTitle && !trimmedTitle.startsWith("http")) return trimmedTitle;

  const urlValue = sourceUrl?.trim() || trimmedTitle;
  if (!urlValue) return "";

  try {
    const url = new URL(urlValue);
    const path =
      url.pathname.length > maxPathLength
        ? `${url.pathname.slice(0, Math.max(maxPathLength - 3, 0))}...`
        : url.pathname;
    return url.hostname + (path === "/" ? "" : path);
  } catch {
    return urlValue.slice(0, maxFallbackLength);
  }
}

export function getKnowledgeSourceSearchText(reference: FlowRunDebugRagReference): string {
  return [
    reference.display_title,
    reference.source_display_name,
    reference.title,
    reference.source_url,
    reference.source_container_name,
    reference.source_container_display_name,
    reference.source_container_label,
    reference.id_short,
    reference.id
  ]
    .filter((value): value is string => typeof value === "string")
    .join(" ")
    .toLowerCase();
}
