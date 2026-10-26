import { render } from "svelte/server";
import { describe, expect, test } from "vitest";
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

  test("renders bot protection without ambient browser credentials", () => {
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
    const configuration = body.match(/<altcha-widget[^>]*configuration="([^"]+)"/);
    expect(configuration).not.toBeNull();
    expect(JSON.parse(configuration![1].replaceAll("&quot;", '"'))).toMatchObject({
      credentials: "omit"
    });
  });
});
