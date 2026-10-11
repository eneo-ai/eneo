/**
 * Whether the flow lets its runs' evidence be downloaded. Off until the flow
 * says yes; the server enforces the same rule for every caller, so only an
 * exact `true` is read as a yes.
 */
export function flowAllowsEvidenceExport(metadataJson: unknown): boolean {
  if (!metadataJson || typeof metadataJson !== "object") return false;
  const evidencePolicy = (metadataJson as Record<string, unknown>).evidence_policy;
  if (!evidencePolicy || typeof evidencePolicy !== "object") return false;
  return (evidencePolicy as Record<string, unknown>).allow_export === true;
}

export function withEvidenceExportAllowed<T extends object>(
  metadataJson: T,
  allowed: boolean
): T & { evidence_policy: { allow_export: boolean } } {
  return { ...metadataJson, evidence_policy: { allow_export: allowed } };
}
