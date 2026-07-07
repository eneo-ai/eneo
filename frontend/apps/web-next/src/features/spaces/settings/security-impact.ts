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
  | "mcp_servers";

const IMPACT_KEYS: SpaceSecurityImpactKey[] = [
  "assistants",
  "group_chats",
  "apps",
  "services",
  "completion_models",
  "embedding_models",
  "transcription_models",
  "mcp_servers"
];

export type SpaceSecurityImpactRow = {
  key: SpaceSecurityImpactKey;
  count: number;
};

export function securityImpactRows(impact: SpaceSecurityImpact): SpaceSecurityImpactRow[] {
  return IMPACT_KEYS.map((key) => ({ key, count: impact[key]?.length ?? 0 })).filter(
    (row) => row.count > 0
  );
}

export function securityImpactTotal(impact: SpaceSecurityImpact): number {
  return securityImpactRows(impact).reduce((sum, row) => sum + row.count, 0);
}
