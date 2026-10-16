import { describe, expect, it } from "vitest";
import type { Schema } from "@/lib/api/models";
import {
  classifyPolicyRefresh,
  isDirtyPolicyDraft,
  isValidPolicyDraft,
  policyDraft,
  unitForBytes
} from "./storage-policy";

const policy: Schema<"DeploymentPolicyPublic"> = {
  policy: {
    revision: 4,
    new_write_storage_target: "postgres_inline",
    session_file_limit_bytes: 1024,
    session_image_limit_bytes: 2048,
    knowledge_file_limit_bytes: 4096,
    transcription_audio_limit_bytes: 8192,
    moves_paused: false,
    updated_by_actor: "storage_admin",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z"
  },
  limits: [],
  capabilities: []
};

describe("storage policy draft", () => {
  it("keeps the backend revision and every limit in a replacement", () => {
    expect(policyDraft(policy)).toEqual({
      expected_revision: 4,
      new_write_storage_target: "postgres_inline",
      session_file_limit_bytes: 1024,
      session_image_limit_bytes: 2048,
      knowledge_file_limit_bytes: 4096,
      transcription_audio_limit_bytes: 8192
    });
  });

  it("accepts only positive safe integer byte limits", () => {
    const draft = policyDraft(policy);
    expect(isValidPolicyDraft(draft)).toBe(true);
    expect(isValidPolicyDraft({ ...draft, session_file_limit_bytes: 0 })).toBe(false);
    expect(isValidPolicyDraft({ ...draft, session_file_limit_bytes: 1.5 })).toBe(false);
    expect(
      isValidPolicyDraft({ ...draft, session_file_limit_bytes: Number.MAX_SAFE_INTEGER + 1 })
    ).toBe(false);
  });

  it("tracks target and limit changes without confusing revision changes with edits", () => {
    const draft = policyDraft(policy);
    expect(isDirtyPolicyDraft(draft, policy)).toBe(false);
    expect(isDirtyPolicyDraft({ ...draft, new_write_storage_target: "object_store" }, policy)).toBe(
      true
    );
    expect(isDirtyPolicyDraft({ ...draft, knowledge_file_limit_bytes: 8192 }, policy)).toBe(true);
  });

  it("starts display units at an exact byte divisor", () => {
    expect(unitForBytes(1048576)).toBe("MB");
    expect(unitForBytes(1536)).toBe("B");
  });

  it("requires a reload when the policy changed while a draft was open", () => {
    expect(classifyPolicyRefresh(4, 5, true)).toBe("stale");
    expect(classifyPolicyRefresh(4, 4, true)).toBe("apply");
    expect(classifyPolicyRefresh(4, 3, false)).toBe("ignore");
    expect(classifyPolicyRefresh(4, 5, false)).toBe("apply");
  });
});
