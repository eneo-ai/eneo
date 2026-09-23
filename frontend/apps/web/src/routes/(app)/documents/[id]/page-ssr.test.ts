import { render } from "svelte/server";
import { describe, expect, test, vi } from "vitest";

const DOCUMENT_ID = "bbbbbbbb-0000-4000-8000-000000000002";

vi.mock("$app/state", () => ({
  // Inline: `vi.mock` factories are hoisted above module-level constants.
  page: { url: new URL("https://eneo.kommun.se/documents/bbbbbbbb-0000-4000-8000-000000000002") }
}));
vi.mock("$lib/core/Eneo", () => ({ getEneo: () => ({}) }));

import DocumentPage from "./+page.svelte";

const empty = { id: DOCUMENT_ID, blob: null, group: null, website: null, space: null };

describe("document reference page on the server", () => {
  // A reference copied from a widget answer is opened by pasting it, so the
  // first render is always a full page load on the server.
  test("renders a pasted reference the reader may not see", () => {
    const { body } = render(DocumentPage, { props: { data: empty } as never });

    expect(body).toContain(`${DOCUMENT_ID} – https://eneo.kommun.se/documents/${DOCUMENT_ID}`);
  });

  test("renders a document with the same reference text the widget copies", () => {
    const blob = {
      id: DOCUMENT_ID,
      text: "Taxan gäller från 1 januari.",
      metadata: { title: "Taxa plan- och bygglov.pdf", url: null },
      original_available: false
    };

    const { body } = render(DocumentPage, { props: { data: { ...empty, blob } } as never });

    expect(body).toContain(
      `Taxa plan- och bygglov.pdf – https://eneo.kommun.se/documents/${DOCUMENT_ID}`
    );
  });
});
