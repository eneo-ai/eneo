import { render } from "svelte/server";
import { describe, expect, test } from "vitest";
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
});
