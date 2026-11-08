import type { Schema } from "@/lib/api/models";

export type SpaceSecurityImpact = Schema<"UpdateSpaceDryRunResponse">;

export type SpaceSecurityImpactKey =
  | "assistants"
  | "group_chats"
  | "apps"
  | "services"
  | "completion_models"
  | "embedding_models"
  | "transcription_models"
  | "mcp_servers"
  | "capabilities";

const IMPACT_KEYS: SpaceSecurityImpactKey[] = [
  "assistants",
  "group_chats",
  "apps",
  "services",
  "completion_models",
  "embedding_models",
  "transcription_models",
  "mcp_servers",
  "capabilities"
];

export type SpaceSecurityImpactRow = {
  key: SpaceSecurityImpactKey;
  count: number;
  names: string[];
};

export function securityImpactRows(impact: SpaceSecurityImpact | null): SpaceSecurityImpactRow[] {
  return IMPACT_KEYS.flatMap((key) => {
    const names =
      key === "capabilities"
        ? (impact?.capabilities ?? [])
        : (impact?.[key] ?? []).map((resource) =>
            "nickname" in resource && typeof resource.nickname === "string" && resource.nickname
              ? resource.nickname
              : resource.name
          );
    return names.length > 0 ? [{ key, count: names.length, names }] : [];
  });
}

export function securityImpactTotal(impact: SpaceSecurityImpact | null): number {
  return securityImpactRows(impact).reduce((sum, row) => sum + row.count, 0);
}
