import { render } from "svelte/server";
import { describe, expect, it } from "vitest";

import { m } from "$lib/paraglide/messages";

import FlowRunEvidenceSummary from "./FlowRunEvidenceSummary.svelte";

describe("FlowRunEvidenceSummary", () => {
  it("shows recorded model and transcription usage in the audited evidence view", () => {
    const { body } = render(FlowRunEvidenceSummary, {
      props: {
        runStatus: "completed",
        tokenUsage: {
          num_tokens_input: 21,
          num_tokens_output: 8,
          num_tokens_total: 29,
          input_completeness: "complete",
          output_completeness: "complete"
        },
        transcriptionUsage: {
          audio_seconds: 51,
          recording_seconds: 51,
          completeness: "complete"
        }
      }
    });

    expect(body).toContain(m.flow_run_tokens_badge({ count: "29" }));
    expect(body).toContain(m.flow_run_audio_badge({ duration: "0:51" }));
  });
});
