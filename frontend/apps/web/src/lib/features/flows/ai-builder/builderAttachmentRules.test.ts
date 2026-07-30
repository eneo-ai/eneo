import type { Limits } from "@eneo/eneo-js";
import { describe, expect, it } from "vitest";

import { getAIBuilderAttachmentRules } from "./builderAttachmentRules";

describe("getAIBuilderAttachmentRules", () => {
  it("uses the resolved backend attachment count", () => {
    const limits: Limits = {
      info_blobs: { formats: [] },
      attachments: {
        formats: [],
        ai_builder_max_count: 37,
        ai_builder_max_message_chars: 12_000
      }
    };

    expect(getAIBuilderAttachmentRules(limits).maxTotalCount).toBe(37);
  });
});
