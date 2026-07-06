// Copyright (c) 2026 Sundsvalls Kommun

// Shape of a single entity row returned by `eneo.models.getUsageDetails`.
// Shared by the migration impact preview and the read-only usage tab so both
// render the same breakdown via `ModelUsageBreakdown.svelte`.
export type UsageDetail = {
  entity_id: string;
  entity_name: string;
  entity_type: string;
  space_name: string | null;
  owner_name: string | null;
};
