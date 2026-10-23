import type { InfoBlob } from "@eneo/eneo-js";
import { render } from "svelte/server";
import { expect, it } from "vitest";
import LinkReference from "./LinkReference.svelte";

function blob(url: string | null): InfoBlob {
  return {
    id: "a",
    metadata: { url, title: "Riktlinje" },
    source_metadata: []
  } as unknown as InfoBlob;
}

it("links to a stored http(s) address", () => {
  const { body } = render(LinkReference, { props: { blob: blob("https://kommun.se/riktlinje") } });

  expect(body).toContain('href="https://kommun.se/riktlinje"');
});

it("never renders a stored script address as a link", () => {
  const { body } = render(LinkReference, {
    props: { blob: blob("javascript:alert(document.cookie)") }
  });

  expect(body.toLowerCase()).not.toContain("javascript:");
  expect(body).not.toContain("href=");
});
