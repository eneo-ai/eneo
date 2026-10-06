import type { Schema } from "@/lib/api/models";

export type DeploymentPolicy = Schema<"DeploymentPolicyPublic">;
export type PolicyUpdate = Schema<"DeploymentPolicyUpdate">;
export type StorageKind = Schema<"StorageKind">;

export function policyDraft(policy: DeploymentPolicy): PolicyUpdate {
  return {
    expected_revision: policy.policy.revision,
    new_write_storage_target: policy.policy.new_write_storage_target,
    session_file_limit_bytes: policy.policy.session_file_limit_bytes,
    session_image_limit_bytes: policy.policy.session_image_limit_bytes,
    knowledge_file_limit_bytes: policy.policy.knowledge_file_limit_bytes,
    transcription_audio_limit_bytes: policy.policy.transcription_audio_limit_bytes
  };
}

export function isValidByteLimit(value: number): boolean {
  return Number.isSafeInteger(value) && value > 0;
}

export function isValidPolicyDraft(draft: PolicyUpdate): boolean {
  return [
    draft.session_file_limit_bytes,
    draft.session_image_limit_bytes,
    draft.knowledge_file_limit_bytes,
    draft.transcription_audio_limit_bytes
  ].every(isValidByteLimit);
}

export function isDirtyPolicyDraft(draft: PolicyUpdate, policy: DeploymentPolicy): boolean {
  const current = policyDraft(policy);
  return (
    draft.new_write_storage_target !== current.new_write_storage_target ||
    draft.session_file_limit_bytes !== current.session_file_limit_bytes ||
    draft.session_image_limit_bytes !== current.session_image_limit_bytes ||
    draft.knowledge_file_limit_bytes !== current.knowledge_file_limit_bytes ||
    draft.transcription_audio_limit_bytes !== current.transcription_audio_limit_bytes
  );
}

/** A newer server revision cannot silently replace an administrator's unsaved draft. */
export function classifyPolicyRefresh(
  currentRevision: number,
  nextRevision: number,
  preserveDraft: boolean
): "ignore" | "stale" | "apply" {
  if (nextRevision < currentRevision) return "ignore";
  if (preserveDraft && nextRevision > currentRevision) return "stale";
  return "apply";
}

export function unitForBytes(value: number): "B" | "KB" | "MB" | "GB" {
  if (value % 1024 ** 3 === 0) return "GB";
  if (value % 1024 ** 2 === 0) return "MB";
  if (value % 1024 === 0) return "KB";
  return "B";
}

export const UNIT_BYTES = { B: 1, KB: 1024, MB: 1024 ** 2, GB: 1024 ** 3 } as const;
