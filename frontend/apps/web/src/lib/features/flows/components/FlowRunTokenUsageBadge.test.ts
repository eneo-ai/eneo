import { render } from "svelte/server";
import { describe, expect, it } from "vitest";

import { m } from "$lib/paraglide/messages";

import FlowRunTokenUsageBadge from "./FlowRunTokenUsageBadge.svelte";

describe("FlowRunTokenUsageBadge", () => {
  it("renders an explicit marker for incomplete usage", () => {
    const { body } = render(FlowRunTokenUsageBadge, {
      props: {
        interactive: false,
        tokenUsage: {
          num_tokens_input: 21,
          num_tokens_output: 8,
          num_tokens_total: 29,
          input_completeness: "incomplete",
          output_completeness: "complete"
        }
      }
    });

    expect(body).toContain(m.flow_run_token_usage_incomplete());
  });

  it("renders not recorded when usage is absent", () => {
    const { body } = render(FlowRunTokenUsageBadge, {
      props: { interactive: false, tokenUsage: null }
    });

    expect(body).toContain(m.flow_run_token_usage_not_recorded());
  });
});
