import { render } from "svelte/server";
import { describe, expect, test, vi } from "vitest";
import EmbedApp from "$lib/features/widget/components/EmbedApp.svelte";
import EmbedPage from "./+page.svelte";

const data = {
  config: null,
  unavailable: false,
  publicId: "wgt_x",
  baseUrl: "http://backend",
  hostOrigin: "https://www.kommun.se",
  preview: false,
  hostScheme: null,
  standalone: false
};

describe("embed page on the server", () => {
  // The loader opens whatever the frame shows; each state is a page of its own.
  test.each([
    ["a paused widget", { ...data, unavailable: true }],
    ["a preview still loading", { ...data, preview: true }]
  ])("gives %s a main landmark", (_state, props) => {
    const { body } = render(EmbedPage, { props: { data: props } as never });

    expect(body).toMatch(/<main[\s>]/);
  });

  test("renders an ALTCHA-protected chat without starting verification on the server", () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(() => {
      throw new Error("Verification must wait for the visitor's first message");
    });
    try {
      const { body } = render(EmbedApp, {
        props: {
          publicId: "wgt_x",
          baseUrl: "https://eneo.example",
          hostOrigin: "https://www.kommun.se",
          hostScheme: null,
          config: {
            public_id: "wgt_x",
            name: "Public assistant",
            texts: {},
            theme: {},
            persona: {},
            language: "en",
            bot_protection: "altcha",
            max_question_chars: 2000,
            token_generation: 0,
            show_sources: true,
            show_tool_activity: true,
            collects_feedback_text: false,
            single_turn: false,
            frame_ancestors: []
          }
        }
      });
      expect(body).toContain("Public assistant");
      expect(fetch).not.toHaveBeenCalled();
    } finally {
      fetch.mockRestore();
    }
  });
});
